import { AlertTriangle, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import {
  formatBRL,
  origemLabel,
  parcelasSaldoInicial,
  type Projection,
  runwayLabel,
  toPolylinePoints,
  trajectoryPoints,
} from "./projecao";

/**
 * Projeção de fluxo de caixa 30/60/90 dias + runway (Story 5.7) — regime de CAIXA. Read-only: só lê
 * a projeção do backend (não escreve nada). Design "Portal": três cartões (janelas) + runway em
 * destaque + gráfico simples da trajetória do saldo.
 *
 * **Story 8.1 (AC5) — a tela declara a procedência e não afirma o que o backend calou.** O saldo
 * inicial vem com `saldo_inicial_origem` e o rótulo aparece colado ao número; quando a origem é
 * `plataforma`, o backend já devolve `runway.days = null` + `days_suprimido` e `alert = false` +
 * `alert_suprimido` por janela. Aqui NÃO existe nenhuma regra de supressão duplicada: a tela só
 * respeita os flags. Se um dia esta tela voltar a mostrar dias/vermelho, é porque a origem mudou
 * (Story 8.8) — não porque alguém "consertou" o frontend.
 *
 * **Story 8.8 (AC5) — a origem mudou, e a tela não precisou aprender nada sobre isso.** Com conta
 * bancária cadastrada o backend devolve `saldo_inicial_origem = "misto"` e as flags de supressão em
 * `false`; o runway em dias, o alerta vermelho e o ícone de tendência voltam **sozinhos**, porque
 * nunca houve regra de supressão duplicada aqui. A ÚNICA adição desta story ao componente é
 * exibir as **duas parcelas** do saldo inicial ao lado do total (`parcelasSaldoInicial`) — somar
 * plano 3 + plano 1 só é autorizado com a composição visível (design §6.1). Nenhuma condicional de
 * `days_suprimido`/`alert_suprimido` foi tocada.
 */
export default function ProjecaoCaixaPage() {
  const [projection, setProjection] = useState<Projection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get<Projection>("/financial-intelligence/projection")
      .then((r) => setProjection(r.data))
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Financeiro / Projeção de caixa</p>
        <h1 className="text-2xl font-bold text-neutral-800">Projeção de fluxo de caixa</h1>
        {/* Story 8.8 (AC5): a frase "Partindo do disponível atual da Carteira" saiu daqui — ela
            deixou de ser verdade quando existe conta bancária cadastrada, e uma apresentação
            estática não tem como saber qual é o caso antes de a resposta chegar. Mesmo movimento
            que a Story 8.1 fez com `_NOTE_CAIXA` no backend: quem afirma a procedência é o campo
            que a carrega (aqui, o cartão abaixo), não um texto de abertura que ninguém revisa. */}
        <p className="mt-1 max-w-2xl text-sm text-neutral-500">
          Para onde o caixa caminha em 30, 60 e 90 dias — em regime de caixa (data de pagamento
          prevista dos lançamentos em aberto). O saldo de partida vem declarado abaixo, com as
          parcelas que o compõem.
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      {loading && <p className="text-sm text-neutral-400">Carregando projeção…</p>}

      {projection && (
        <>
          <RunwayCard projection={projection} />

          <div className="grid gap-4 sm:grid-cols-3">
            {projection.windows.map((w) => (
              <WindowCard
                key={w.days}
                days={w.days}
                cents={w.saldo_projetado_cents}
                alert={w.alert}
                alertSuprimido={w.alert_suprimido}
                origem={projection.saldo_inicial_origem}
              />
            ))}
          </div>

          <TrajectoryChart projection={projection} />

          {(projection.overdue_inflow_cents > 0 || projection.overdue_outflow_cents > 0) && (
            <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-700 ring-1 ring-amber-200">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <p>
                A projeção inclui itens <strong>vencidos e ainda em aberto</strong> como caixa
                esperado imediato: {formatBRL(projection.overdue_inflow_cents)} a receber e{" "}
                {formatBRL(projection.overdue_outflow_cents)} a pagar em atraso. Recebíveis vencidos
                podem não se concretizar — leia a projeção com cautela.
              </p>
            </div>
          )}

          {projection.notes.length > 0 && (
            <ul className="space-y-1 text-xs text-neutral-400">
              {projection.notes.map((n) => (
                <li key={n}>• {n}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function RunwayCard({ projection }: { projection: Projection }) {
  const { runway, saldo_inicial_cents, saldo_inicial_origem } = projection;
  // Três estados, nunca dois (Story 8.1, AC4/AC5): suprimido ≠ sem risco ≠ número de dias.
  const suprimido = runway.days_suprimido;
  const semRisco = !suprimido && runway.days === null;
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Runway (fôlego de caixa)</p>
          <p
            className={`mt-1 text-3xl font-bold ${
              semRisco ? "text-emerald-600" : suprimido ? "text-neutral-500" : "text-neutral-800"
            }`}
          >
            {runwayLabel(runway)}
          </p>
          <p className="mt-1 text-xs text-neutral-400">
            {semRisco
              ? "O caixa não está sendo queimado no horizonte projetado."
              : `Queima de ${formatBRL(runway.burn_rate_cents_per_day)} por dia no ritmo atual.`}
          </p>
          {suprimido && (
            // A queima diária (acima) continua visível e válida — ela vem das contas em aberto.
            // O que não temos é o saldo de partida certo, e por isso não dizemos quantos dias faltam.
            <p className="mt-2 max-w-md text-xs text-amber-700">
              O saldo inicial é o {origemLabel(saldo_inicial_origem)}, não o da sua conta bancária —
              por isso o e1p não diz quantos dias de fôlego você tem. Cadastre sua conta para que
              essa leitura volte a ter lastro.
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-sm text-neutral-500">Saldo inicial de hoje</p>
          <p className="mt-1 text-xl font-semibold text-neutral-800">
            {formatBRL(saldo_inicial_cents)}
          </p>
          {/* AC1/AC5: a procedência viaja colada ao número, nunca em outra parte da tela. */}
          <p className="mt-0.5 text-xs text-neutral-400">{origemLabel(saldo_inicial_origem)}</p>
          <ParcelasSaldoInicial projection={projection} />
        </div>
      </div>
    </div>
  );
}

/**
 * As parcelas do saldo inicial, logo abaixo do total (Story 8.8, AC5).
 *
 * **Somar sim; esconder a composição, nunca.** Quando a origem é `misto`, o total é a soma de dois
 * planos de dinheiro diferentes e o design §6.1 só autoriza essa soma com as parcelas visíveis —
 * "no banco" e "na plataforma (a liberar/sacar)". A decisão de QUAIS parcelas exibir é da função
 * pura `parcelasSaldoInicial` (testada em `projecao.test.ts`); aqui só se desenha.
 *
 * Quando há uma parcela só (o fallback `plataforma`), a lista não é renderizada: repetir o total
 * logo abaixo dele mesmo seria ruído, e a procedência já está dita na linha de origem acima.
 *
 * ⚠️ Cores NEUTRAS de propósito. Verde/vermelho aqui seriam uma afirmação sobre o saldo, e a única
 * afirmação desta área é "de onde o dinheiro vem" — a lição do ícone de tendência da Story 8.1.
 */
function ParcelasSaldoInicial({ projection }: { projection: Projection }) {
  const parcelas = parcelasSaldoInicial(projection);
  if (parcelas.length < 2) return null;
  return (
    <dl className="mt-2 space-y-0.5 text-xs text-neutral-500">
      {parcelas.map((p) => (
        <div key={p.rotulo} className="flex justify-end gap-2">
          <dt>{p.rotulo}</dt>
          <dd className="font-medium text-neutral-700">{formatBRL(p.cents)}</dd>
        </div>
      ))}
    </dl>
  );
}

function WindowCard({
  days,
  cents,
  alert,
  alertSuprimido,
  origem,
}: {
  days: number;
  cents: number;
  alert: boolean;
  alertSuprimido: boolean;
  origem: string;
}) {
  // Story 8.1 (AC4b): quando o veredito é suprimido, o cartão para de gritar vermelho — mas o
  // NÚMERO continua exibido, com o rótulo de origem. Suprima a afirmação, nunca o número.
  //
  // ⚠️ O ÍCONE TAMBÉM É UMA AFIRMAÇÃO — a 3ª superfície contaminada da story (as duas primeiras
  // foram `runway.days` e o `alert`). `cents >= 0 → TrendingUp verde` é o MESMO cruzamento de
  // limiar sobre a MESMA soma contaminada que o `alert`, só que com polaridade invertida e em
  // verde. Como `available_cents` só cresce (`request_payout` apenas marca `withdrawn`), o saldo
  // projetado sai inflado e a seta verde para cima aparece justamente nas janelas em que o caixa
  // verdadeiro pode estar apertado: o mesmo falso negativo do D-5, vestido de glifo. Sob supressão,
  // ícone e cor neutros (`Minus`) — o e1p mostra o número e não afirma tendência nenhuma.
  return (
    <div
      className={`rounded-2xl p-5 shadow-sm ${
        alert ? "bg-red-50 ring-1 ring-red-200" : "bg-white"
      }`}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500">Em {days} dias</p>
        {alert ? (
          <AlertTriangle size={18} className="text-danger" />
        ) : alertSuprimido ? (
          <Minus size={18} className="text-neutral-400" aria-label="Tendência não informada" />
        ) : cents >= 0 ? (
          <TrendingUp size={18} className="text-emerald-500" />
        ) : (
          <TrendingDown size={18} className="text-neutral-400" />
        )}
      </div>
      <p className={`mt-2 text-2xl font-bold ${alert ? "text-danger" : "text-neutral-800"}`}>
        {formatBRL(cents)}
      </p>
      <p className="mt-1 text-xs text-neutral-400">
        {alert
          ? "Caixa fica negativo nesta janela"
          : alertSuprimido
            ? `Saldo projetado a partir do ${origemLabel(origem)}`
            : "Saldo projetado"}
      </p>
    </div>
  );
}

const CHART_W = 640;
const CHART_H = 160;

function TrajectoryChart({ projection }: { projection: Projection }) {
  const points = useMemo(() => trajectoryPoints(projection), [projection]);
  const poly = useMemo(
    () => toPolylinePoints(points, { width: CHART_W, height: CHART_H, padding: 12 }),
    [points],
  );
  // As mesmas coordenadas da polyline, parseadas para desenhar os marcadores nos vértices.
  const coords = useMemo(
    () => (poly ? poly.split(" ").map((p) => p.split(",").map(Number)) : []),
    [poly],
  );
  // Story 8.1 (AC4b): `anyAlert` passa a ignorar janelas suprimidas DE GRAÇA — o backend já devolve
  // `alert = false` nelas. Nenhuma condicional nova aqui é proposital: uma segunda regra de
  // supressão no frontend seria justamente a duplicação que a supressão-na-origem existe para
  // evitar. A trajetória continua desenhando os saldos reais (o número não é suprimido), só não é
  // traçada em vermelho — a cor é uma afirmação, a linha é o dado.
  const anyAlert = projection.windows.some((w) => w.alert);
  const stroke = anyAlert ? "#dc2626" : "#5D44F8"; // vermelho se alguma janela zera; senão cor Portal

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">Trajetória do saldo</p>
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="mt-3 h-40 w-full"
        role="img"
        aria-label="Gráfico da trajetória do saldo de caixa projetado ao longo de 90 dias"
        preserveAspectRatio="none"
      >
        <polyline points={poly} fill="none" stroke={stroke} strokeWidth={2.5} />
        {coords.map(([x, y], i) => (
          <circle key={points[i].days} cx={x} cy={y} r={3.5} fill={stroke} />
        ))}
      </svg>
      <div className="mt-2 flex justify-between text-xs text-neutral-400">
        <span>Hoje</span>
        <span>30d</span>
        <span>60d</span>
        <span>90d</span>
      </div>
    </div>
  );
}
