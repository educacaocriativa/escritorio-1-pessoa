"""Quais componentes de um nome de cliente podem virar marcador na pergunta do dono.

O problema, medido: `_nomes_conhecidos` quebra cada nome da carteira em componentes de 3+ letras
e manda mascarar todos. Num CRM de pequeno negócio brasileiro, **nome de cliente é palavra
comum** — com "Bar do Porto", "Casa Nova Reformas" e "Sol Nascente Ltda" na carteira, a pergunta

    quanto gastei no bar esse mes? preciso pagar a casa e comprar sol e sombra

chegava à Claude assim:

    quanto gastei no [PESSOA_3] esse mes? preciso pagar a [PESSOA_1] e comprar [PESSOA_2] e sombra

A resposta piora e ninguém descobre por quê — não há erro, só uma pergunta que virou charada.
`Ltda` era o caso mais caro: toda empresa na carteira fazia "ltda" virar marcador em QUALQUER
pergunta.

**A garantia não muda.** O nome COMPLETO ("Bar do Porto") continua sempre mascarado, por
`mask_literals`, antes de qualquer componente. O que esta lista faz é decidir se o componente
ISOLADO ("bar") também vira marcador — e a resposta é não, quando ele é palavra de todo dia.

Por que uma lista, e não "mascarar só o que for incomum": decidir incomum exige um dicionário
PT-BR (dependência nova) ou uma varredura do corpus do tenant a cada pergunta (latência, e mais
consulta sob RLS). As duas são probabilísticas, e o docstring de `_nomes_conhecidos` já rejeitou
o probabilístico ao escolher vocabulário determinístico em vez de NER. Uma lista versionada é
auditável: dá para ver o que ela cobre, e o custo de errar é uma palavra a mais mascarada.

A lista é um piso, não um teto — quem descobrir um falso positivo novo acrescenta a palavra aqui.
"""
from __future__ import annotations

import unicodedata

# ── Termos societários ────────────────────────────────────────────────────────────────────
# O grupo de maior impacto: aparecem em quase todo nome de pessoa jurídica, então mascaravam a
# palavra em TODA pergunta de quem tem empresas na carteira. (Os de 1-2 letras — "me", "sa",
# "ss" — nunca chegaram aqui, porque o filtro de componentes já exige 3+ letras; ficam listados
# para que a lista continue correta se aquele filtro mudar.)
_SOCIETARIOS = """
me sa ss ltda ltd epp mei eireli cia inc llc sociedade empresa empresas empreendimentos
comercio comercial industria industrial servicos produtos solucoes assessoria consultoria
representacoes distribuidora distribuicao atacado varejo filial matriz grupo holding
participacoes associados associacao instituto fundacao cooperativa
"""

# ── Ramos de negócio ──────────────────────────────────────────────────────────────────────
# Palavras que nomeiam o negócio E aparecem na pergunta com o sentido comum ("gastei no bar",
# "passar na farmácia").
_RAMOS = """
bar restaurante lanchonete padaria mercado mercearia supermercado hortifruti acougue
farmacia drogaria loja lojas oficina garagem salao barbearia estetica clinica consultorio
escritorio academia escola colegio curso creche hotel pousada pizzaria hamburgueria
sorveteria cafe cafeteria papelaria livraria floricultura petshop lavanderia imobiliaria
construtora transportadora borracharia marcenaria serralheria grafica estudio atelie
boutique joalheria otica banca quiosque buffet bufe eventos festa festas viagens turismo
seguros contabilidade advocacia odontologia veterinaria
"""

# ── Vocabulário de todo dia ───────────────────────────────────────────────────────────────
# Substantivos, adjetivos e advérbios de alta frequência que também batizam negócio ("Casa
# Nova", "Sol Nascente", "Bom Preço"). Não entram aqui palavras que só um nome próprio
# explicaria — "Porto" e "Nascente" continuam mascaráveis de propósito.
_COTIDIANO = """
casa lar sol lua mar campo centro cidade vila jardim parque praca rua avenida ponto lugar
canto esquina porta janela mesa agua terra luz vida flor cor verde azul branco preto
vermelho amarelo ouro prata bom boa bem mal melhor pior novo nova velho grande pequeno
alto baixo forte fraco primeiro segundo terceiro ultimo proximo antigo real
dia dias mes meses ano anos hoje ontem amanha semana semanas hora horas minuto tempo vez
vezes manha tarde noite cedo agora ainda sempre nunca depois antes durante
"""

# ── Vocabulário do negócio ────────────────────────────────────────────────────────────────
# O assunto das perguntas da Vima. "Conta", "Caixa", "Recanto" e afins também são nome de
# empresa, e mascará-los apagava justamente o substantivo que dava sentido à pergunta.
_NEGOCIO = """
cliente clientes contato contatos fornecedor conta contas caixa banco saldo valor valores
dinheiro preco custo custos despesa despesas receita receitas lucro prejuizo pagamento
pagamentos cobranca cobrancas fatura faturas boleto nota notas pedido pedidos orcamento
orcamentos proposta contrato contratos venda vendas compra compras produto servico trabalho
trabalhos negocio projeto projetos obra obras reforma reformas entrega entregas estoque
agenda compromisso compromissos reuniao reunioes consulta consultas horario prazo vencimento
imposto impostos folha salario comissao meta metas relatorio resumo total mensal anual
"""

# ── Palavras funcionais e verbos frequentes ───────────────────────────────────────────────
_FUNCIONAIS = """
da das de do dos em na nas no nos ao aos com sem sob sobre para pelo pela pelos pelas por
que quem qual quais quanto quantos quanta
quantas como onde quando porque entao tambem apenas mesmo mesma outro outra outros outras
cada algum alguma alguns algumas nenhum nenhuma nada tudo todo toda todos todas mais menos
muito muita muitos muitas pouco pouca varios varias ambos ate desde entre contra
ser sou somos sao esta estao estou estamos estava estavam esteve ter tem tenho temos tinha
teve fazer faz faco fiz fez fazia ir vou vai vamos foi fui vir vem venho dar dou deu ver
vejo viu saber sei sabe poder posso pode queria quero quer preciso precisa precisamos devo
deve pagar pago paguei receber recebo recebi comprar compro comprei vender vendo
vendi gastar gasto gastei ganhar ganho ganhei mandar mando mandei enviar envio enviei falar
falo falei ligar ligo liguei marcar marco marquei agendar cancelar abrir fechar entrar sair
ficar passar chegar levar trazer colocar pegar deixar achar olhar mostrar criar montar usar
"""


def _normalizar(palavra: str) -> str:
    """Minúsculas, sem acento e sem pontuação de borda.

    Sem isso a lista precisaria de "servicos" E "serviços", e `Cia.` (com o ponto que sobra do
    `split()`) escaparia de `cia`.
    """
    sem_acento = "".join(
        letra
        for letra in unicodedata.normalize("NFD", palavra.casefold())
        if unicodedata.category(letra) != "Mn"
    )
    return sem_acento.strip(".,;:!?()[]{}\"'“”‘’-–—/&")


PALAVRAS_COMUNS: frozenset[str] = frozenset(
    _normalizar(palavra)
    for bloco in (_SOCIETARIOS, _RAMOS, _COTIDIANO, _NEGOCIO, _FUNCIONAIS)
    for palavra in bloco.split()
)

# Comprimento mínimo do componente. Herdado do código anterior: abaixo disso a chance de o
# componente ser palavra comum supera de longe a de ele identificar alguém.
TAMANHO_MINIMO_DO_COMPONENTE = 3


def componentes_mascaraveis(nomes: list[str]) -> set[str]:
    """Componentes isolados que ainda vale a pena mascarar, dado o vocabulário da carteira.

    Recebe os nomes COMPLETOS e devolve só as partes que não são palavra comum — "Porto" e
    "Nascente" entram, "Bar", "Casa", "Sol" e "Ltda" não. Quem chama continua mascarando os
    nomes completos separadamente; esta função não decide nada sobre eles.
    """
    return {
        parte
        for nome in nomes
        for parte in nome.split()
        if len(parte) >= TAMANHO_MINIMO_DO_COMPONENTE
        and _normalizar(parte) not in PALAVRAS_COMUNS
        and _normalizar(parte) != ""
    }
