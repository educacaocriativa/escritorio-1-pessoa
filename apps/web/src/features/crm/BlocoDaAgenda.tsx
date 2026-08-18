import type { AgendaEvent } from "@e1p/shared-types";
import { CalendarPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { formatDateTime, formatDay } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import EscolherHorario from "../agenda/EscolherHorario";
import NewEventModal from "../agenda/NewEventModal";

/**
 * O que está MARCADO com este contato — irmão do `BlocoDaConversa` (o que foi DITO) e do
 * `ClientTimeline` (o que ACONTECEU). Três perguntas diferentes, três blocos diferentes.
 *
 * É o bloco ATIVO da ficha: só mostra o FUTURO (o passado já vive no Histórico, Task 4) e traz o
 * botão "Marcar com este cliente" para o dono agir sem sair da tela. O estado vazio é o mais
 * importante dos dois — "Nenhum compromisso marcado" é o sinal de um contato esfriando no funil.
 */
export default function BlocoDaAgenda({ clientId, nome }: { clientId: string; nome: string }) {
  const fuso = useFuso();
  const [eventos, setEventos] = useState<AgendaEvent[]>([]);
  const [erro, setErro] = useState(false);
  const [carregando, setCarregando] = useState(true);
  // Dois passos, dois estados: primeiro o dono vê a agenda (`escolhendo`), depois preenche o
  // formulário (`escolha`). `escolha` guardar o dia (e a hora, quando veio de uma faixa) é o que
  // faz o formulário nascer preenchido.
  const [escolhendo, setEscolhendo] = useState(false);
  // `seq` é o que faz o `key` do formulário MUDAR a cada escolha — inclusive quando o dono
  // reescolhe exatamente o mesmo dia e a mesma hora. Sem ele, a chave se repetiria e o React
  // reusaria a instância suja.
  const [escolha, setEscolha] = useState<{ dia: Date; hora: number | null; seq: number } | null>(
    null,
  );

  const load = useCallback(async () => {
    // Falha aqui NÃO pode derrubar a ficha — mesma postura do `BlocoDaConversa`: degrada para um
    // aviso em vez de levar junto Cobranças, Contratos e o resto da tela.
    try {
      // `start=agora` filtra no SERVIDOR (`list_events`: `ends_at >= start`), o mesmo critério do
      // `next_event_map` que alimenta o card do Kanban — inclui o evento de dia inteiro de HOJE
      // (cujo `starts_at` já ficou no passado à meia-noite, mas `ends_at` ainda não). Um corte
      // client-side por `starts_at >= agora` reintroduziria esse bug. O backend já devolve
      // ordenado por `starts_at` ascendente (mais próximo primeiro); nada a reordenar aqui.
      //
      // `exclude_cancelled=true`: este bloco é o único dos três (Histórico, next_event_map e
      // este) que ainda deixava um compromisso CANCELADO se passar por "próximo compromisso" —
      // e é exatamente o sinal que o estado vazio existe para revelar (contato esfriando sem
      // próximo passo). O default do endpoint é `false` (a tela de Agenda continua mostrando
      // cancelados no calendário); aqui pedimos explicitamente o filtro.
      const agora = new Date().toISOString();
      const { data } = await api.get<AgendaEvent[]>(
        `/agenda/events?client_id=${encodeURIComponent(clientId)}&start=${encodeURIComponent(agora)}&exclude_cancelled=true`,
      );
      setEventos(Array.isArray(data) ? data : []);
      setErro(false);
    } catch {
      setErro(true);
      setEventos([]);
    } finally {
      setCarregando(false);
    }
  }, [clientId]);

  useEffect(() => {
    load();
  }, [load]);

  if (carregando) return <p className="py-4 text-sm text-neutral-400">Carregando agenda...</p>;
  if (erro) {
    return (
      <p className="py-4 text-sm text-amber-700">
        Não foi possível carregar a agenda.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {eventos.length === 0 ? (
        <p className="py-2 text-center text-sm text-neutral-400">Nenhum compromisso marcado</p>
      ) : (
        <ul className="divide-y divide-neutral-100">
          {eventos.map((e) => (
            <li key={e.id} className="py-2.5">
              {/* `break-words`: o título vem de digitação livre e pode chegar sem espaço, hífen
                  ou barra (o dono grudando o nome de um fornecedor, por exemplo) — sem quebra de
                  palavra o texto vaza a caixa em vez de quebrar linha (achado da régua de 360px,
                  Onda 2 Task 8: `forcaFora` de 439px com um título assim). */}
              <p className="break-words text-sm font-medium text-neutral-800">{e.title}</p>
              {/* Dia inteiro é DATA DE CALENDÁRIO (gravada à meia-noite UTC): formata pela
                  string, sem `Date`, para não "voltar" um dia em fuso negativo. Com horário é
                  INSTANTE: converte para o fuso do tenant — nunca `localYmd` aqui (ver a nota
                  do próprio helper em `lib/datetime.ts`). */}
              <p className="text-xs text-neutral-400">
                {e.all_day ? formatDay(e.starts_at) : formatDateTime(e.starts_at, fuso)}
              </p>
            </li>
          ))}
        </ul>
      )}

      <button
        onClick={() => setEscolhendo(true)}
        className="flex w-full items-center justify-center gap-1.5 rounded-pill bg-primary-50 py-2 text-sm font-semibold text-primary-600 hover:bg-primary-100"
      >
        <CalendarPlus size={14} /> Marcar com este cliente
      </button>

      {/* Passo 1 — "quando dá?". Mostra o mês do dono e as faixas livres do dia. Só depois de
          uma escolha o formulário aparece: era aqui que o dono marcava às cegas. */}
      <EscolherHorario
        open={escolhendo}
        nome={nome}
        onClose={() => setEscolhendo(false)}
        onEscolher={(dia, hora) => {
          setEscolha((anterior) => ({ dia, hora, seq: (anterior?.seq ?? 0) + 1 }));
          setEscolhendo(false);
        }}
      />

      {/* Passo 2 — reusa o `NewEventModal` da Task 5, que já cuida do aviso de conflito,
          mantendo-se aberto quando a API reporta sobreposição para o dono decidir. `onCreated`
          só recarrega a lista; o próprio modal chama `onClose` quando não há conflito.
          O aviso de conflito continua importando mesmo com o seletor na frente: a agenda pode ter
          mudado entre abrir o mês e salvar, e o seletor não conhece compromisso fora de 08–18h. */}
      {/* ⚠️ O `key` NÃO é enfeite. O `NewEventModal` fica montado o tempo todo e guarda estado
          próprio; só `startDate`/`start`/`end` são reescritos ao abrir. `allDay`, título,
          descrição, convidados e o aviso de conflito sobreviviam de uma abertura para a outra — e
          um "Dia inteiro" herdado faz o `save()` DESCARTAR a hora que o dono acabou de apontar na
          faixa livre, em silêncio. É o mesmo defeito que o `NewBillModal` já pagou com `key`, e a
          primeira abertura de cada sessão sempre funciona, o que é o que o esconde num teste
          manual apressado. */}
      <NewEventModal
        key={escolha?.seq ?? 0}
        open={escolha !== null}
        initialDate={escolha?.dia ?? null}
        initialHour={escolha?.hora ?? null}
        onClose={() => setEscolha(null)}
        onCreated={load}
        clientId={clientId}
      />
    </div>
  );
}
