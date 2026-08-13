"""§6.5 — a derivação do progresso, com controle positivo.

Sem um caso em que `k > 0`, o teste passa verde num script que devolve zero para sempre — a
família do §2 do Epic 8 (o teste que passa e não prova nada), e o mesmo cuidado que
`test_volume_nao_altera_a_divergencia` tomou.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.scripts import nucleo_activation as na

REGISTER = {
    "legal_name": "Script ME",
    "document": "11444777000161",
    "slug": "scriptme",
    "email": "script@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}


def _e(action: str, target: str, minuto: int) -> AuditEntry:
    """Uma entrada com `created_at` EXPLÍCITO.

    ⚠️ Não semeie pela rota HTTP aqui: `created_at` vem de `server_default=func.now()`, que no
    SQLite tem resolução de SEGUNDO — quatro chamadas no mesmo segundo saem com o mesmo carimbo e
    a ordem passaria a depender do desempate por uuid, que é arbitrário. O teste mediria o acaso.
    """
    return AuditEntry(
        tenant_id="t",
        actor="u",
        action=action,
        target=target,
        created_at=datetime(2026, 8, 11, 12, minuto, tzinfo=UTC),
    )


def test_uma_passagem_completa_com_k_maior_que_zero():
    """O controle positivo: `respondidas` PRECISA ser > 0 em algum caso."""
    passagens = na.derivar(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "nucleo:oferta.o_que_vende", 1),
            _e("dna.answer.save", "nucleo:oferta.em_uma_frase", 2),
            _e("dna.answer.skip", "nucleo:oferta.como_cobra", 3),
            _e("dna.nucleo.abandon", "", 4),
        ]
    )

    assert len(passagens) == 1
    p = passagens[0]
    assert p.exibidas == 6
    assert p.respondidas == 2
    assert p.puladas == 1
    assert p.abandonou is True
    assert p.fim == datetime(2026, 8, 11, 12, 4, tzinfo=UTC)


def test_resposta_de_outra_origem_nao_conta_como_progresso_do_nucleo():
    """É PARA ISSO que o `source` vive no `target`.

    O não-membro: uma pergunta respondida na aba de `/config` no meio de uma passagem do núcleo
    não é progresso do núcleo. Sem o recorte por prefixo, ela seria contada e o denominador
    passaria a mentir.
    """
    [p] = na.derivar(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "config:oferta.ticket_tipico", 1),
            _e("dna.answer.save", "gancho:dinheiro.cobranca_antecedencia_dias", 2),
            _e("dna.answer.save", "nucleo:oferta.o_que_vende", 3),
        ]
    )

    assert p.respondidas == 1
    assert p.abandonou is False
    assert p.fim is None


def test_duas_passagens_do_mesmo_dono_nao_se_misturam():
    """Um dono que abandonou no celular e depois abriu no desktop deixa DOIS `open` (§7)."""
    passagens = na.derivar(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "nucleo:oferta.o_que_vende", 1),
            _e("dna.nucleo.abandon", "", 2),
            _e("dna.nucleo.open", "5", 10),
            _e("dna.answer.save", "nucleo:oferta.em_uma_frase", 11),
        ]
    )

    assert [(p.exibidas, p.respondidas, p.abandonou) for p in passagens] == [
        (6, 1, True),
        (5, 1, False),
    ]


def test_resposta_antes_de_qualquer_open_nao_inventa_passagem():
    """Gancho e `/config` acontecem fora do núcleo o tempo todo, e não são passagem nenhuma."""
    assert na.derivar([_e("dna.answer.save", "gancho:oferta.como_cobra", 0)]) == []


def test_respostas_por_origem_separa_as_tres_portas():
    """A evidência sobre a quarentena de 7 dias e o "uma por dia" (a meia dívida da §0.1)."""
    contagem = na.respostas_por_origem(
        [
            _e("dna.nucleo.open", "6", 0),
            _e("dna.answer.save", "nucleo:a", 1),
            _e("dna.answer.skip", "gancho:b", 2),
            _e("dna.answer.save", "config:c", 3),
            _e("dna.answer.save", "config:d", 4),
        ]
    )

    assert contagem == {"nucleo": 1, "gancho": 1, "config": 2}


def test_o_fim_da_passagem_e_dito_por_extenso():
    """A saída não pode largar uma data solta e esperar que o leitor adivinhe o que ela é.

    Achado lendo o primeiro relatório real com o fundador (2026-08-13): a linha do abandono saía
    como `respondidas 0 · puladas 0 · 12/08/2026 08:47`, e só dava para deduzir o significado
    comparando com a linha que dizia "sem abandono registrado". É a classe de erro que este
    projeto mais documenta — o artefato cujo consumidor é um humano num ciclo futuro.

    Membro e não-membro escritos, no mesmo teste.
    """
    abandonada = na.Passagem(
        abertura=datetime(2026, 8, 12, 11, 47, tzinfo=UTC),
        exibidas=6,
        fim=datetime(2026, 8, 12, 11, 47, tzinfo=UTC),
    )
    concluida = na.Passagem(abertura=datetime(2026, 8, 13, 19, 14, tzinfo=UTC), exibidas=6)

    frase = na.situacao_do_fim(abandonada, "America/Sao_Paulo")

    # A data continua lá, e agora vem NOMEADA — e no fuso do tenant (11:47Z == 08:47 em SP).
    assert frase == "abandonou em 12/08/2026 08:47"
    assert na.situacao_do_fim(concluida, "America/Sao_Paulo") == "sem abandono registrado"


def test_o_rodape_diz_QUANTOS_TENANTS_foram_varridos():
    """A lição literal do `investment_audit.py`.

    `0 em 0 tenants` e `0 em 7 tenants` são resultados DIFERENTES, e o primeiro é defeito do
    próprio script. Um rodapé que não carrega o denominador não distingue os dois.
    """
    vazio = na.rodape(passagens=0, tenants=0, abandonos=0)
    povoado = na.rodape(passagens=0, tenants=7, abandonos=0)

    assert vazio != povoado
    assert "0 tenant" in vazio
    assert "7 tenant" in povoado


def test_entradas_do_dna_le_so_o_que_e_do_dna(client: TestClient, db: Session):
    """A query real, contra o banco de teste — e o não-membro ao lado.

    ⚠️ **Asserção por CONJUNTO, não por lista, e não é preguiça.** `created_at` vem de
    `server_default=func.now()`, que no SQLite tem resolução de SEGUNDO: as duas chamadas HTTP
    abaixo caem no mesmo carimbo, e aí a ordem passa a ser decidida pelo desempate por `id`, que é
    um uuid — arbitrário. Afirmar ordem aqui seria **testar o acaso** (a primeira versão deste
    teste fazia isso e falhou na primeira execução). O que esta função promete é o RECORTE; a
    ordem é promessa da query e é exercitada onde ela pode ser fixada, nos testes de `derivar`
    acima, com `created_at` explícito. É a mesma distinção do histórico de saques da Onda 3: no
    SQLite o teste afirma estabilidade, e a cronologia de verdade se afirma onde há microssegundo.
    """
    headers = {
        "Authorization": "Bearer "
        + client.post("/auth/register", json=REGISTER).json()["access_token"]
    }
    client.post("/dna/nucleo/open", json={"exibidas": 6}, headers=headers)
    client.put(
        "/dna/oferta.ticket_tipico", json={"valor": "2k_10k", "source": "nucleo"}, headers=headers
    )
    # O não-membro: uma action de OUTRO módulo, na mesma tabela, não pode entrar na leitura.
    db.add(AuditEntry(tenant_id="t", actor="u", action="bank.account.create", target="xyz"))
    db.commit()

    acoes = [e.action for e in na.entradas_do_dna(db)]

    assert sorted(acoes) == ["dna.answer.save", "dna.nucleo.open"]
    # O não-membro, dito por extenso: a action de outro módulo existe na tabela e ficou de fora.
    assert "bank.account.create" not in acoes
