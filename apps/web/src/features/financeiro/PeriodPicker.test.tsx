import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PeriodPicker from "./PeriodPicker";
import { resolvePeriod, type PeriodRange } from "./periodRange";

/**
 * Espelha os QUATRO call sites reais (`DrePage`, `LucratividadePage`, `ConferenciaPage`,
 * `ContasSaldosPage`): todos guardam o período num `useState(() => resolvePeriod("this_year"))`
 * e passam o par `value`/`onChange` direto. Nenhum deles mexe no período por fora do picker,
 * então o `value` que o componente recebe é SEMPRE o eco da sua própria última mudança.
 * `em-vigor` é o período que o pai está de fato usando para consultar o backend.
 */
function Pai({ inicial }: { inicial: PeriodRange }) {
  const [range, setRange] = useState<PeriodRange>(inicial);
  return (
    <>
      <PeriodPicker value={range} onChange={setRange} />
      <output data-testid="em-vigor">{`${range.start}..${range.end}`}</output>
    </>
  );
}

const seletor = () => screen.getByLabelText("Período");
const inicio = () => screen.getByLabelText("Início do período personalizado");
const fim = () => screen.getByLabelText("Fim do período personalizado");

describe("PeriodPicker", () => {
  beforeEach(() => {
    // Instante congelado: sem ele, "Este mês"/"Este ano" mudam de valor conforme o calendário
    // da máquina e o teste vira um oráculo diferente a cada mês. 21/08/2026, 15:00Z — a suíte
    // roda em America/Sao_Paulo e `resolvePeriod` lê o relógio em UTC, então o mês é agosto.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-21T15:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reabrir 'Personalizado' mostra o intervalo EM VIGOR, não o da montagem", () => {
    render(<Pai inicial={resolvePeriod("this_year")} />);

    fireEvent.change(seletor(), { target: { value: "this_month" } });
    fireEvent.change(seletor(), { target: { value: "custom" } });

    expect(inicio()).toHaveValue("2026-08-01");
    expect(fim()).toHaveValue("2026-08-31");
  });

  it("abrir 'Personalizado' NÃO troca o período em vigor por baixo do dono", () => {
    // O lado do dinheiro do mesmo defeito: o pai refaz a consulta ao backend a cada troca de
    // `period` (`useCallback([period, …])`), então um intervalo velho aplicado aqui não é só um
    // campo mal preenchido — é a DRE inteira voltando para o ano quando o dono pediu o mês.
    render(<Pai inicial={resolvePeriod("this_year")} />);

    fireEvent.change(seletor(), { target: { value: "this_month" } });
    expect(screen.getByTestId("em-vigor")).toHaveTextContent("2026-08-01..2026-08-31");

    fireEvent.change(seletor(), { target: { value: "custom" } });
    expect(screen.getByTestId("em-vigor")).toHaveTextContent("2026-08-01..2026-08-31");
  });

  it("digitar no campo personalizado não fecha o campo debaixo do dedo", () => {
    // Mata o conserto alternativo — pôr o intervalo na `key` do componente. Como cada tecla já
    // chama `onChange`, uma `key` derivada do `value` remontaria o picker a CADA dígito: o
    // `shortcut` voltaria a "Este ano", os dois campos de data sumiriam da tela e o foco iria
    // junto. O precedente por `key` do repo (`NewBillModal`, `pagar/PagarPage.tsx`) é legítimo
    // lá porque aquilo é um MODAL, que nasce e morre por abertura; este aqui fica montado.
    render(<Pai inicial={resolvePeriod("this_year")} />);
    fireEvent.change(seletor(), { target: { value: "custom" } });

    inicio().focus();
    fireEvent.change(inicio(), { target: { value: "2026-03-01" } });

    expect(screen.queryByLabelText("Início do período personalizado")).not.toBeNull();
    expect(inicio()).toHaveValue("2026-03-01");
    expect(document.activeElement).toBe(inicio());
  });

  it("abrir 'Personalizado' não dispara consulta nova — o pai depende da IDENTIDADE do objeto", () => {
    // `DrePage`/`LucratividadePage` fecham o `load` num `useCallback([period, …])`. Um `onChange`
    // com os MESMOS valores mas objeto novo passa pela igualdade referencial do React e refaz a
    // consulta à toa. Abrir o campo para ajustar não é ainda um pedido de período novo.
    const onChange = vi.fn();
    render(<PeriodPicker value={resolvePeriod("this_year")} onChange={onChange} />);

    fireEvent.change(seletor(), { target: { value: "custom" } });

    expect(onChange).not.toHaveBeenCalled();
    expect(inicio()).toHaveValue("2026-01-01");
  });

  it("o que o dono digita vira o período em vigor, campo a campo", () => {
    render(<Pai inicial={resolvePeriod("this_year")} />);
    fireEvent.change(seletor(), { target: { value: "custom" } });

    fireEvent.change(inicio(), { target: { value: "2026-03-01" } });
    expect(screen.getByTestId("em-vigor")).toHaveTextContent("2026-03-01..2026-12-31");

    fireEvent.change(fim(), { target: { value: "2026-06-30" } });
    expect(screen.getByTestId("em-vigor")).toHaveTextContent("2026-03-01..2026-06-30");
  });
});
