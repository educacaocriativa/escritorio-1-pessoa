"""O catálogo do DNA da Empresa — as 45 perguntas, em código.

Catálogo em código pelo mesmo critério de `LIMIARES_PADRAO` (vima/absences.py) e
`MODELO_POR_TAREFA` (core/ai.py): o que precisa de gate de teste mora onde o teste alcança.
Pergunta nova exige deploy, e isso é correto — pergunta de Calibração vem sempre junto do
consumidor dela, que é código de qualquer forma.

**As duas classes são um contrato, não uma etiqueta de organização:**

- `CALIBRACAO` tem consumidor HOJE. Responder muda o briefing de amanhã.
- `RETRATO` não tem, por definição. É guardado para o V4.

A guarda abaixo roda no IMPORT do módulo. Sem ela, em seis meses alguém marca uma pergunta
bonita como Calibração, o dono a responde acreditando ter mudado o comportamento do produto, e
não mudou nada — um produto que finge ouvir é pior que um produto que não pergunta.

Este módulo é PURO: não lê relógio, não toca no banco. Ver o gate em
`tests/test_fuso_do_tenant.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.vima.absences import LIMIARES_PADRAO

CALIBRACAO = "calibracao"
RETRATO = "retrato"

FORMATO_ESCOLHA = "escolha"
FORMATO_MULTIPLA = "escolha_multipla"
FORMATO_TEXTO = "texto"

EIXOS = ("oferta", "cliente", "ritmo", "dinheiro", "limites")

# Teto do campo aberto. Não é limite de banco (a coluna é JSON) — é o ponto em que o texto
# deixou de ser resposta e virou documento, e o V4 vai ter que resumi-lo de qualquer forma.
MAX_TEXTO = 2000


class CatalogoError(ValueError):
    """Violação do contrato das classes. Estoura no import, não em produção."""


@dataclass(frozen=True)
class Opcao:
    rotulo: str              # o que o dono lê
    valor: int | str | None  # o que o sistema guarda e consome


@dataclass(frozen=True)
class Pergunta:
    key: str
    classe: str
    eixo: str
    texto: str
    formato: str
    opcoes: tuple[Opcao, ...] = field(default_factory=tuple)
    consome: str | None = None
    gancho: str | None = None


def verificar(perguntas: tuple[Pergunta, ...]) -> None:
    """As guardas. Pública para que o teste as exercite sobre catálogo arbitrário.

    Um teste que só olhasse `PERGUNTAS` provaria que o catálogo de hoje está certo, não que a
    guarda funciona — e a guarda é o que protege o catálogo de amanhã.
    """
    vistas: set[str] = set()
    for p in perguntas:
        if p.key in vistas:
            raise CatalogoError(f"key duplicada: {p.key}")
        vistas.add(p.key)

        if p.eixo not in EIXOS:
            raise CatalogoError(f"{p.key}: eixo '{p.eixo}' não existe")
        if not p.key.startswith(f"{p.eixo}."):
            raise CatalogoError(f"{p.key} não começa com o eixo '{p.eixo}'")

        if p.classe == CALIBRACAO:
            if not p.consome:
                raise CatalogoError(
                    f"{p.key} é Calibração e não declara consumidor — a classe existe "
                    "justamente para impedir pergunta sem efeito"
                )
            if p.consome not in LIMIARES_PADRAO:
                raise CatalogoError(
                    f"{p.key} consome '{p.consome}', ausente de LIMIARES_PADRAO. Um typo aqui "
                    "grava a resposta, não consome nada e nunca falha."
                )
        elif p.classe == RETRATO:
            if p.consome:
                raise CatalogoError(f"{p.key} é Retrato e declara consumidor '{p.consome}'")
        else:
            raise CatalogoError(f"{p.key}: classe '{p.classe}' não existe")

        if p.formato == FORMATO_ESCOLHA and len(p.opcoes) < 2:
            raise CatalogoError(f"{p.key} é escolha com menos de duas opções")


def _cal(key, eixo, texto, opcoes, consome, gancho) -> Pergunta:
    return Pergunta(
        key=key, classe=CALIBRACAO, eixo=eixo, texto=texto, formato=FORMATO_ESCOLHA,
        opcoes=opcoes, consome=consome, gancho=gancho,
    )


def _esc(key, eixo, texto, opcoes, gancho=None) -> Pergunta:
    return Pergunta(
        key=key, classe=RETRATO, eixo=eixo, texto=texto, formato=FORMATO_ESCOLHA,
        opcoes=opcoes, gancho=gancho,
    )


def _mult(key, eixo, texto, opcoes, gancho=None) -> Pergunta:
    return Pergunta(
        key=key, classe=RETRATO, eixo=eixo, texto=texto, formato=FORMATO_MULTIPLA,
        opcoes=opcoes, gancho=gancho,
    )


def _txt(key, eixo, texto, gancho=None) -> Pergunta:
    return Pergunta(
        key=key, classe=RETRATO, eixo=eixo, texto=texto, formato=FORMATO_TEXTO, gancho=gancho,
    )


# --- Calibração (6) --------------------------------------------------------------------
# Cada uma existe porque há um número esperando por ela. São SEIS porque só existem seis
# consumidores — qualquer número maior seria invenção.

_CALIBRACAO: tuple[Pergunta, ...] = (
    _cal(
        "ritmo.resposta_horas", "ritmo",
        "Um cliente te escreveu e ficou sem resposta. Em quanto tempo eu te aviso?",
        (
            Opcao("Em 4 horas", 4),
            Opcao("No mesmo dia", 12),
            Opcao("No dia seguinte", 24),
            Opcao("Depois de 2 dias", 48),
        ),
        "sem_resposta_nossa_horas",
        "briefing.ausencia.comercial.contato.esperando_resposta",
    ),
    _cal(
        "cliente.esfria_dias", "cliente",
        "Quantos dias sem falar com um cliente já significa que ele esfriou?",
        (Opcao("15 dias", 15), Opcao("30 dias", 30), Opcao("60 dias", 60), Opcao("90 dias", 90)),
        "contato_sumido_dias",
        "briefing.ausencia.comercial.contato.sumido",
    ),
    _cal(
        "ritmo.card_parado_dias", "ritmo",
        "Uma negociação parada na mesma etapa há quanto tempo te incomoda?",
        (Opcao("5 dias", 5), Opcao("10 dias", 10), Opcao("20 dias", 20), Opcao("30 dias", 30)),
        "card_parado_dias",
        "briefing.ausencia.comercial.card.parado",
    ),
    _cal(
        "cliente.topo_seco_dias", "cliente",
        "Quantos dias sem nenhum cliente novo é anormal no seu negócio?",
        (
            Opcao("3 dias", 3),
            Opcao("5 dias", 5),
            Opcao("15 dias", 15),
            # A ÚNICA regra que pode ser desligada: é a única que dispara sobre o VAZIO. As
            # outras cinco se calam sozinhas em quem não usa aquilo — sem cards, não há card
            # parado. `None` = regra não executada (mesma forma do filtro de permissão do V1,
            # que não roda a regra em vez de calcular e esconder).
            Opcao("Não quero esse aviso", None),
        ),
        "topo_sem_lead_dias",
        "briefing.ausencia.comercial.topo.sem_lead",
    ),
    _cal(
        "ritmo.prazo_antecedencia_dias", "ritmo",
        "Com quanta antecedência você quer saber de um prazo?",
        (
            Opcao("No próprio dia", 0),
            Opcao("1 dia antes", 1),
            Opcao("3 dias antes", 3),
            Opcao("1 semana antes", 7),
        ),
        "prazo_vencendo_dias",
        "briefing.ausencia.agenda.prazo.estourado",
    ),
    _cal(
        "dinheiro.antecedencia_dias", "dinheiro",
        "E de uma conta a pagar?",
        (
            Opcao("No próprio dia", 0),
            Opcao("1 dia antes", 1),
            Opcao("3 dias antes", 3),
            Opcao("1 semana antes", 7),
        ),
        "dinheiro_com_data_dias",
        "briefing.ausencia.financeiro.conta.vencendo",
    ),
)

# --- Retrato (39) ----------------------------------------------------------------------
# Regra de pertencimento: entra se um funcionário humano recém-contratado precisaria saber no
# primeiro dia. "Qual seu CNPJ" não entra (é cadastro, mora em tenant_profiles).

_OFERTA: tuple[Pergunta, ...] = (
    _esc(
        "oferta.o_que_vende", "oferta", "O que você vende?",
        (
            Opcao("Serviço recorrente", "servico_recorrente"),
            Opcao("Serviço por projeto", "servico_projeto"),
            Opcao("Produto físico", "produto_fisico"),
            Opcao("Produto digital", "produto_digital"),
            Opcao("Um pouco de cada", "misto"),
        ),
    ),
    _txt(
        "oferta.em_uma_frase", "oferta",
        "Se um cliente perguntar o que você faz, o que você responde?",
    ),
    _esc(
        "oferta.ticket_tipico", "oferta", "Quanto costuma custar um trabalho seu?",
        (
            Opcao("Até R$ 500", "ate_500"),
            Opcao("R$ 500 a 2 mil", "500_2k"),
            Opcao("R$ 2 mil a 10 mil", "2k_10k"),
            Opcao("R$ 10 mil a 50 mil", "10k_50k"),
            Opcao("Acima de R$ 50 mil", "acima_50k"),
        ),
        gancho="quotes.orcamento.criado",
    ),
    _esc(
        "oferta.prazo_entrega", "oferta",
        "Do 'sim' do cliente até a entrega, quanto tempo costuma passar?",
        (
            Opcao("No mesmo dia", "mesmo_dia"),
            Opcao("Até uma semana", "semana"),
            Opcao("De 2 a 4 semanas", "mes"),
            Opcao("Mais de um mês", "mais_de_um_mes"),
            Opcao("É contínuo, não tem fim", "continuo"),
        ),
    ),
    _esc(
        "oferta.como_cobra", "oferta", "Como você costuma cobrar?",
        (
            Opcao("Tudo antes", "antes"),
            Opcao("Tudo depois", "depois"),
            Opcao("Entrada e saldo", "entrada_saldo"),
            Opcao("Parcelado", "parcelado"),
            Opcao("Mensalidade", "mensalidade"),
        ),
    ),
    _esc(
        "oferta.capacidade_mes", "oferta",
        "Quantos clientes novos você consegue atender por mês, no máximo?",
        (
            Opcao("1 ou 2", "1_2"),
            Opcao("3 a 5", "3_5"),
            Opcao("6 a 15", "6_15"),
            Opcao("Mais de 15", "mais_15"),
            Opcao("Não tenho teto", "sem_teto"),
        ),
    ),
    _esc(
        "oferta.proposta_formal", "oferta",
        "Você manda proposta ou orçamento escrito antes de fechar?",
        (
            Opcao("Sempre", "sempre"),
            Opcao("Na maioria das vezes", "maioria"),
            Opcao("Raramente", "raramente"),
            Opcao("Nunca", "nunca"),
        ),
        gancho="quotes.orcamento.criado",
    ),
    _txt("oferta.diferencial", "oferta", "Por que um cliente escolhe você e não o concorrente?"),
    _txt("oferta.aberta", "oferta", "Algo mais que a Vima precisa saber sobre o que você vende?"),
)

_CLIENTE: tuple[Pergunta, ...] = (
    _esc(
        "cliente.quem_e", "cliente", "Quem compra de você?",
        (
            Opcao("Pessoa física", "pf"),
            Opcao("Pequenas empresas", "pequenas"),
            Opcao("Empresas médias e grandes", "grandes"),
            Opcao("Órgãos públicos", "publico"),
            Opcao("Um pouco de cada", "misto"),
        ),
        gancho="crm.cliente.criado",
    ),
    _mult(
        "cliente.como_chega", "cliente", "Como o cliente chega até você?",
        (
            Opcao("Indicação", "indicacao"),
            Opcao("Redes sociais", "social"),
            Opcao("Busca no Google", "busca"),
            Opcao("Anúncio pago", "ads"),
            Opcao("Prospecção ativa", "outbound"),
            Opcao("Passagem ou loja física", "fisico"),
        ),
    ),
    _esc(
        "cliente.decisao_tempo", "cliente",
        "Do primeiro contato até o cliente decidir, quanto tempo costuma levar?",
        (
            Opcao("No mesmo dia", "mesmo_dia"),
            Opcao("Poucos dias", "dias"),
            Opcao("De 1 a 4 semanas", "semanas"),
            Opcao("Mais de um mês", "meses"),
        ),
        gancho="crm.cliente.criado",
    ),
    _esc(
        "cliente.recompra", "cliente", "O mesmo cliente costuma voltar?",
        (
            Opcao("É recorrente por contrato", "contrato"),
            Opcao("Volta com frequência", "frequente"),
            Opcao("Volta às vezes", "as_vezes"),
            Opcao("É compra única", "unica"),
        ),
    ),
    _esc(
        "cliente.objecao", "cliente", "O que mais faz um cliente dizer não?",
        (
            Opcao("Preço", "preco"),
            Opcao("Prazo", "prazo"),
            Opcao("Falta de confiança", "confianca"),
            Opcao("Não era o que ele procurava", "fit"),
            Opcao("Ele some sem dizer nada", "some"),
        ),
    ),
    _esc(
        "cliente.canal_preferido", "cliente", "Por onde o cliente prefere falar com você?",
        (
            Opcao("WhatsApp", "whatsapp"),
            Opcao("Telefone", "telefone"),
            Opcao("E-mail", "email"),
            Opcao("Presencial", "presencial"),
            Opcao("Instagram e afins", "social"),
        ),
    ),
    _txt("cliente.sinal_de_que_fecha", "cliente", "O que te faz saber que um cliente vai fechar?"),
    _txt("cliente.aberta", "cliente", "Algo mais que a Vima precisa saber sobre seus clientes?"),
)

_RITMO: tuple[Pergunta, ...] = (
    _mult(
        "ritmo.dias_de_trabalho", "ritmo", "Em que dias você trabalha?",
        (
            Opcao("Segunda", "seg"), Opcao("Terça", "ter"), Opcao("Quarta", "qua"),
            Opcao("Quinta", "qui"), Opcao("Sexta", "sex"), Opcao("Sábado", "sab"),
            Opcao("Domingo", "dom"),
        ),
    ),
    _esc(
        "ritmo.janela_do_dia", "ritmo", "Que horas você costuma trabalhar?",
        (
            Opcao("De manhã", "manha"),
            Opcao("Horário comercial", "comercial"),
            Opcao("Tarde e noite", "tarde_noite"),
            Opcao("De madrugada", "madrugada"),
            Opcao("Varia muito", "varia"),
        ),
    ),
    _esc(
        "ritmo.pico_do_mes", "ritmo", "Tem época do mês mais cheia?",
        (
            Opcao("Começo", "comeco"), Opcao("Meio", "meio"),
            Opcao("Fim", "fim"), Opcao("Não tem padrão", "sem_padrao"),
        ),
    ),
    _txt("ritmo.sazonalidade", "ritmo", "E do ano? Tem mês que enche e mês que esvazia?"),
    _esc(
        "ritmo.o_que_trava", "ritmo", "O que mais trava o seu dia?",
        (
            Opcao("Atender cliente", "atender"),
            Opcao("Fazer o trabalho em si", "executar"),
            Opcao("Cobrar", "cobrar"),
            Opcao("Burocracia", "burocracia"),
            Opcao("Vender", "vender"),
        ),
    ),
    _esc(
        "ritmo.sozinho", "ritmo", "Você trabalha sozinho?",
        (
            Opcao("Sozinho", "sozinho"),
            Opcao("Com ajuda pontual de freelas", "freelas"),
            Opcao("Tenho 1 ou 2 pessoas", "pequena"),
            Opcao("Tenho equipe", "equipe"),
        ),
    ),
    _txt("ritmo.aberta", "ritmo", "Algo mais que a Vima precisa saber sobre o seu ritmo?"),
)

_DINHEIRO: tuple[Pergunta, ...] = (
    _esc(
        "dinheiro.atraso_reacao", "dinheiro", "Cliente atrasou o pagamento. O que você faz?",
        (
            Opcao("Cobro no dia seguinte", "imediato"),
            Opcao("Espero alguns dias", "espero"),
            Opcao("Espero ele falar", "passivo"),
            Opcao("Evito cobrar", "evito"),
        ),
        gancho="receivables.cobranca.criada",
    ),
    # ⚠️ Parece Calibração e NÃO é: tem número e opções fechadas, mas não existe hoje regra de
    # Ausência sobre tolerância a atraso (`dinheiro com data` olha vencimento, não carência).
    # A classe é definida pelo contrato, nunca pelo formato. Se a regra nascer, esta pergunta
    # migra de classe junto com ela — e a guarda cobra que o consumidor exista antes.
    _esc(
        "dinheiro.tolerancia_dias", "dinheiro",
        "Quantos dias de atraso você tolera antes de agir?",
        (
            Opcao("1 dia", 1), Opcao("3 dias", 3), Opcao("7 dias", 7),
            Opcao("15 dias", 15), Opcao("30 dias", 30),
        ),
    ),
    _esc(
        "dinheiro.reserva", "dinheiro", "Você tem reserva para quantos meses parados?",
        (
            Opcao("Nenhuma", "nenhuma"),
            Opcao("Menos de um mês", "menos_1"),
            Opcao("De 1 a 3 meses", "1_3"),
            Opcao("De 3 a 6 meses", "3_6"),
            Opcao("Mais de 6 meses", "mais_6"),
        ),
    ),
    _esc(
        "dinheiro.pro_labore", "dinheiro", "Você tira um valor fixo por mês para você?",
        (
            Opcao("Sim, fixo", "fixo"),
            Opcao("Sim, variável", "variavel"),
            Opcao("Não separo", "nao_separo"),
        ),
    ),
    _txt("dinheiro.sinal_de_aperto", "dinheiro", "O que te diz que o mês vai ser apertado?"),
    _mult(
        "dinheiro.formas_recebimento", "dinheiro", "Como você recebe?",
        (
            Opcao("Pix", "pix"), Opcao("Boleto", "boleto"), Opcao("Cartão", "cartao"),
            Opcao("Dinheiro", "dinheiro"), Opcao("Transferência", "transferencia"),
        ),
        gancho="receivables.cobranca.criada",
    ),
    _esc(
        "dinheiro.emite_nota", "dinheiro", "Você emite nota fiscal?",
        (
            Opcao("Sempre", "sempre"),
            Opcao("Quando o cliente pede", "sob_demanda"),
            Opcao("Não emito", "nao"),
        ),
        gancho="payables.conta.criada",
    ),
    _txt("dinheiro.aberta", "dinheiro", "Algo mais que a Vima precisa saber sobre o seu dinheiro?"),
)

# O eixo mais importante e o mais fácil de esquecer: é o único que o V4 lê para decidir o que
# NÃO fazer sozinho. Autonomia progressiva sem esta lista é um agente que descobre os limites
# errando na frente do cliente.
_LIMITES: tuple[Pergunta, ...] = (
    _txt("limites.nunca_faco", "limites", "O que você nunca faz, mesmo que o cliente peça?"),
    _mult(
        "limites.exige_voce", "limites", "O que só pode sair com você olhando antes?",
        (
            Opcao("Proposta e preço", "proposta"),
            Opcao("Mensagem para cliente", "mensagem"),
            Opcao("Cobrança", "cobranca"),
            Opcao("Contrato", "contrato"),
            Opcao("Publicação", "publicacao"),
            Opcao("Nada disso", "nada"),
        ),
    ),
    _esc(
        "limites.tom", "limites", "Como você fala com cliente?",
        (
            Opcao("Formal", "formal"),
            Opcao("Cordial e direto", "cordial"),
            Opcao("Informal e próximo", "informal"),
            Opcao("Bem-humorado", "humorado"),
        ),
    ),
    _esc(
        "limites.desconto", "limites", "Você dá desconto?",
        (
            Opcao("Nunca", "nunca"),
            Opcao("Só em caso especial", "especial"),
            Opcao("Negocio sempre", "sempre"),
            Opcao("Tenho tabela fixa", "tabela"),
        ),
        gancho="quotes.orcamento.criado",
    ),
    _txt("limites.recusa_cliente", "limites", "Que tipo de cliente você recusa?"),
    _esc(
        "limites.horario_contato", "limites", "Pode falar com cliente fora do seu horário?",
        (
            Opcao("Pode sempre", "sempre"),
            Opcao("Só urgência", "urgencia"),
            Opcao("Nunca", "nunca"),
        ),
        gancho="agenda.evento.criado",
    ),
    _txt("limites.aberta", "limites", "Algo mais que a Vima precisa saber sobre os seus limites?"),
)

PERGUNTAS: tuple[Pergunta, ...] = (
    _CALIBRACAO + _OFERTA + _CLIENTE + _RITMO + _DINHEIRO + _LIMITES
)

# A guarda roda AGORA, no import. Falha na subida do processo, não em produção.
verificar(PERGUNTAS)

POR_KEY: dict[str, Pergunta] = {p.key: p for p in PERGUNTAS}

# O núcleo do primeiro acesso. NENHUMA é de Calibração, e essa é a inversão central do design:
# "em quanto tempo eu te aviso que ninguém respondeu o Carlos?" é impossível de responder bem
# antes de ter visto um briefing. A resposta seria um chute que depois vira comportamento
# errado com aparência de configuração deliberada.
NUCLEO: tuple[str, ...] = (
    "oferta.o_que_vende",
    "oferta.em_uma_frase",
    "oferta.como_cobra",
    "oferta.ticket_tipico",
    "cliente.como_chega",
    "limites.nunca_faco",
)
