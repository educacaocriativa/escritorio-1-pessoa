import type { AgendaEvent } from "@e1p/shared-types";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Modal from "../../components/Modal";
import { api } from "../../lib/api";
import { formatTime, localYmd } from "../../lib/datetime";
import { sentenceCase } from "../../lib/texto";
import { useFuso } from "../../store/auth";
import {
  HORA_ABERTURA,
  HORA_FECHAMENTO,
  WEEKDAYS,
  densidadePorDia,
  eventosDoDia,
  faixasLivres,
  gradeDoMes,
  horaCheia,
  hojeDoTenant,
  paramsDaGrade,
  sameDay,
} from "./grade";

/**
 * "Quando dá?" ANTES de "o que é?".
 *
 * O botão "Marcar com este cliente" da ficha 360° abria o formulário de evento direto: o dono
 * escolhia data e hora sem ver o próprio calendário, e só descobria a colisão depois de salvar,
 * pelo aviso de conflito do `NewEventModal`. Este seletor inverte a ordem — mostra o mês, o que
 * já está marcado no dia e as faixas que sobraram; o formulário só aparece com data e hora já
 * decididas.
 *
 * Não recebe `clientId` de propósito: disponibilidade é a agenda do DONO inteira, não os
 * compromissos deste contato. Filtrar por contato mostraria um mês vazio para quem está com a
 * semana lotada.
 */
export default function EscolherHorario({
  open,
  nome,
  onClose,
  onEscolher,
}: {
  open: boolean;
  /** Nome do contato, só para o título. */
  nome: string;
  onClose: () => void;
  /** `hora` é a hora cheia escolhida, ou `null` quando o dono pediu "Outro horário". */
  onEscolher: (dia: Date, hora: number | null) => void;
}) {
  const fuso = useFuso();
  const [anchor, setAnchor] = useState(() => hojeDoTenant(fuso));
  const [dia, setDia] = useState(() => hojeDoTenant(fuso));
  const [eventos, setEventos] = useState<AgendaEvent[]>([]);
  const [erro, setErro] = useState(false);
  const [parcial, setParcial] = useState(false);

  const { start, end, days } = useMemo(() => gradeDoMes(anchor), [anchor]);

  // Guarda de sequência: aqui o refetch é dirigido por MARTELADA do usuário (dois toques rápidos
  // em "Mês seguinte"), e nada garante que as respostas cheguem na ordem em que foram pedidas. Sem
  // isto, a resposta de um mês antigo chegando por último sobrescreve a do mês visível — e a tela
  // volta a opinar sobre disponibilidade com a lista errada, que é o defeito que o `dia` seguindo
  // o mês (abaixo) acabou de fechar pelo outro lado.
  const pedido = useRef(0);

  const load = useCallback(async () => {
    const meu = ++pedido.current;
    try {
      const { data } = await api.get<AgendaEvent[]>("/agenda/events", {
        params: paramsDaGrade(start, end),
      });
      if (meu !== pedido.current) return;
      const lista = Array.isArray(data) ? data : [];
      setEventos(lista);
      // `limit` é o TETO do endpoint (`le=500`) e não há campo de total: batendo nele, a CAUDA do
      // mês é cortada (o backend ordena por `starts_at`) e aqueles dias apareceriam sem bolinha e
      // com as dez faixas livres — a lista incompleta virando uma DECISÃO de agendamento, em
      // silêncio nas duas pontas. Não paginamos; dizemos que não sabemos.
      setParcial(lista.length >= paramsDaGrade(start, end).limit);
      setErro(false);
    } catch {
      // Sem a agenda não há disponibilidade a mostrar — mas o dono ainda precisa conseguir
      // marcar. Degrada para o aviso + "Outro horário", nunca para uma tela morta.
      if (meu !== pedido.current) return;
      setErro(true);
      setEventos([]);
      setParcial(false);
    }
  }, [start, end]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // Memoizados pela mesma razão da densidade: sem isto, todo toque num dia paga a varredura
  // inteira da janela de 42 dias de novo.
  const doDia = useMemo(() => eventosDoDia(eventos, dia, fuso), [eventos, dia, fuso]);
  const livres = useMemo(() => faixasLivres(eventos, dia, fuso), [eventos, dia, fuso]);
  const hoje = hojeDoTenant(fuso);
  // Uma passada por EVENTO, não uma por célula × evento. `today()` constrói dois
  // `Intl.DateTimeFormat` descartáveis por chamada (~200 µs), e a grade tem 42 células: com 50
  // eventos no mês — trivial num mês com parcelas e contas recorrentes, que viram um
  // `agenda_events` cada — o custo por render passava de 340 ms, e ele se repetia a cada toque
  // num dia. No aparelho de 360px que a feature declara atender, isso é a tela travando.
  const densidade = useMemo(() => densidadePorDia(eventos, fuso), [eventos, fuso]);

  // O dia selecionado ACOMPANHA o mês. Sem isto, `eventos` passava a ser a lista do mês novo
  // enquanto o painel de baixo continuava escrito "15 de outubro" — um dia lotado aparecia com as
  // dez faixas livres, sem nem a célula selecionada na tela para denunciar, e clicar numa faixa
  // marcava em cima de um compromisso existente. Era o oposto exato do que o seletor existe para
  // fazer. Voltar para o mês corrente reencontra HOJE; qualquer outro mês começa no dia 1.
  function irPara(dir: number) {
    const novo = new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1);
    setAnchor(novo);
    setDia(novo.getMonth() === hoje.getMonth() && novo.getFullYear() === hoje.getFullYear() ? hoje : novo);
  }

  return (
    <Modal
      title={`Marcar com ${nome}`}
      open={open}
      testId="seletor-horario"
      onClose={onClose}
      footer={
        // Na barra fixa do rodapé porque é a saída de escape: em 360px a lista de faixas empurra
        // o botão para fora da tela, e sem ele um dia cheio vira um beco sem saída.
        <button
          onClick={() => onEscolher(dia, null)}
          className="min-h-[44px] w-full rounded-pill border border-neutral-200 bg-white text-sm font-semibold text-neutral-600 hover:bg-neutral-50"
        >
          Outro horário
        </button>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <button
              aria-label="Mês anterior"
              onClick={() => irPara(-1)}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-neutral-500 hover:bg-neutral-100"
            >
              <ChevronLeft size={18} />
            </button>
            <button
              aria-label="Mês seguinte"
              onClick={() => irPara(1)}
              className="flex h-11 w-11 items-center justify-center rounded-lg text-neutral-500 hover:bg-neutral-100"
            >
              <ChevronRight size={18} />
            </button>
          </div>
          <h3 className="text-sm font-bold text-neutral-800">{tituloDoMes(anchor)}</h3>
          <button
            onClick={() => {
              setAnchor(hoje);
              setDia(hoje);
            }}
            className="min-h-[44px] rounded-pill border border-neutral-200 px-3 text-xs text-neutral-600 hover:bg-neutral-50"
          >
            Hoje
          </button>
        </div>

        {erro && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
            Não foi possível carregar a agenda — escolha o horário no formulário.
          </p>
        )}

        {!erro && parcial && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
            Mês muito cheio: a agenda pode estar incompleta aqui. Confira antes de confirmar.
          </p>
        )}

        <div>
          <div className="grid grid-cols-7 text-center text-[10px] font-medium text-neutral-400">
            {WEEKDAYS.map((w) => (
              <div key={w} className="py-1">
                {w}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-0.5">
            {days.map((d) => {
              const noMes = d.getMonth() === anchor.getMonth();
              const ocupacao = densidade.get(localYmd(d)) ?? 0;
              const escolhido = sameDay(d, dia);
              return (
                <button
                  key={d.toISOString()}
                  aria-label={rotuloDoDia(d)}
                  aria-pressed={escolhido}
                  onClick={() => setDia(d)}
                  className={`flex aspect-square flex-col items-center justify-center rounded-lg text-xs transition ${
                    escolhido
                      ? "bg-primary-500 font-bold text-white"
                      : noMes
                        ? "text-neutral-700 hover:bg-neutral-100"
                        : "text-neutral-300 hover:bg-neutral-50"
                  } ${!escolhido && sameDay(d, hoje) ? "ring-1 ring-primary-300" : ""}`}
                >
                  <span className="tabular-nums">{d.getDate()}</span>
                  {/* Só a densidade, não o título: o mês inteiro cabe em 360px porque cada dia
                      gasta 3px de altura para dizer "tem coisa aqui". O que é fica no painel
                      abaixo, para o dia que o dono escolheu. */}
                  <span className="mt-0.5 flex h-1 items-center gap-0.5">
                    {Array.from({ length: Math.min(ocupacao, 3) }, (_, i) => (
                      <span
                        key={i}
                        className={`h-1 w-1 rounded-full ${escolhido ? "bg-white/70" : "bg-primary-300"}`}
                      />
                    ))}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="border-t border-neutral-100 pt-3">
          <h4 className="text-sm font-semibold text-neutral-800">{rotuloCompleto(dia)}</h4>

          {doDia.length > 0 && (
            <ul className="mt-2 space-y-1">
              {doDia.map((e) => (
                <li key={e.id} className="flex gap-2 text-xs text-neutral-500">
                  <span className="w-24 shrink-0 tabular-nums">
                    {e.all_day
                      ? "Dia inteiro"
                      : `${formatTime(e.starts_at, fuso)}–${formatTime(e.ends_at, fuso)}`}
                  </span>
                  {/* `break-words`: título é digitação livre e pode vir sem espaço nenhum —
                      mesma razão da lista do `BlocoDaAgenda`. */}
                  <span className="min-w-0 break-words text-neutral-700">{e.title}</span>
                </li>
              ))}
            </ul>
          )}

          {livres.length === 0 ? (
            <p className="mt-3 text-sm text-neutral-400">
              Sem horário livre entre {horaCheia(HORA_ABERTURA)} e {horaCheia(HORA_FECHAMENTO)}{" "}
              neste dia.
            </p>
          ) : (
            <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {livres.map((f) => (
                <button
                  key={f.hora}
                  onClick={() => onEscolher(dia, f.hora)}
                  className="min-h-[44px] rounded-pill bg-primary-50 text-xs font-semibold tabular-nums text-primary-600 hover:bg-primary-100"
                >
                  {f.inicio}–{f.fim}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

const tituloDoMes = (d: Date) =>
  sentenceCase(d.toLocaleDateString("pt-BR", { month: "long", year: "numeric" }));

/** O nome acessível da célula: "15 de outubro" — o número sozinho não diz de que mês é. */
const rotuloDoDia = (d: Date) =>
  d.toLocaleDateString("pt-BR", { day: "numeric", month: "long" });

const rotuloCompleto = (d: Date) =>
  sentenceCase(d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" }));
