"""O compositor decide O QUE entra e em que ordem. A Claude decide apenas COMO dizer."""
from datetime import UTC, datetime

from app.core.facts import COM_FORMULARIO_RECEBIDO, CRM_FUNIL_INSCRITO, CRM_LEAD_CRIADO
from app.modules.vima.composer import compor


def _fato(kind, title, module, client_id=None, quando=None, fid="f1"):
    return type("F", (), {
        "id": fid, "kind": kind, "title": title, "module": module,
        "client_id": client_id, "subject_type": None, "subject_id": None,
        "occurred_at": quando or datetime(2026, 8, 6, 3, 0, tzinfo=UTC),
    })()


def test_colapsa_formulario_e_lead_num_acontecimento_so():
    """Dois fatos, um acontecimento. Ambos ficam GRAVADOS; o colapso é da composição."""
    p = compor(
        fatos=[
            _fato(COM_FORMULARIO_RECEBIDO, "Formulário recebido da página “Consultoria”",
                  "comercial", client_id="c1", fid="f1"),
            _fato(CRM_LEAD_CRIADO, "Chegou pelo site", "crm", client_id="c1", fid="f2"),
        ],
        ausencias=[], tendencias=[], valores={},
    )
    aconteceu = [linha for linha in p.linhas if linha.secao == "ACONTECEU"]
    assert len(aconteceu) == 1
    assert "Consultoria" in aconteceu[0].texto
    assert "funil" in aconteceu[0].texto


def test_agrega_acima_de_tres_repeticoes_da_mesma_frase():
    """Quarenta vezes a MESMA frase é uma notícia, não quarenta."""
    fatos = [
        _fato(CRM_FUNIL_INSCRITO, "Contato entrou na automação “Boas-vindas”",
              "crm", fid=f"f{i}")
        for i in range(40)
    ]
    p = compor(fatos=fatos, ausencias=[], tendencias=[], valores={})
    aconteceu = [linha for linha in p.linhas if linha.secao == "ACONTECEU"]
    assert len(aconteceu) == 1
    assert "40" in aconteceu[0].texto


def test_frases_distintas_do_mesmo_kind_nao_agregam():
    """A contraprova da agregação: cinquenta notas diferentes são cinquenta acontecimentos.

    É o que separa agregar de esconder — o eixo é a frase repetida, não o `kind`.
    """
    fatos = [_fato("crm.nota.criada", f"Nota {i}", "crm", fid=f"f{i}") for i in range(50)]
    p = compor(fatos=fatos, ausencias=[], tendencias=[], valores={}, teto=50)
    assert len([linha for linha in p.linhas if linha.secao == "ACONTECEU"]) == 50


def test_injeta_o_valor_lido_da_origem():
    """A Invariante 2 diz que o FATO não guarda dinheiro. O compositor injeta na composição."""
    f = _fato("financeiro.pagamento.recebido", "Pagamento de João recebido", "financeiro",
              fid="f1")
    f.subject_type, f.subject_id = "charge", "ch1"
    p = compor(fatos=[f], ausencias=[], tendencias=[],
               valores={("charge", "ch1"): "R$ 3.200,00"})
    assert "R$ 3.200,00" in p.linhas[0].texto


def test_corta_no_teto_e_declara_o_excedente():
    fatos = [_fato("crm.nota.criada", f"Nota {i}", "crm", fid=f"f{i}") for i in range(50)]
    p = compor(fatos=fatos, ausencias=[], tendencias=[], valores={}, teto=5)
    assert len([linha for linha in p.linhas if linha.secao == "ACONTECEU"]) == 5
    assert p.excedente == 45


def test_ausencia_vem_antes_de_fato_na_ordem_de_prioridade():
    from app.modules.vima.absences import Ausencia

    p = compor(
        fatos=[_fato(CRM_LEAD_CRIADO, "Chegou pelo site", "crm")],
        ausencias=[Ausencia(module="comercial", kind="comercial.contato.esperando_resposta",
                            title="Carlos esperando sua resposta há 2 dias", dias=2)],
        tendencias=[], valores={},
    )
    assert p.linhas[0].secao == "PENDENTE"
