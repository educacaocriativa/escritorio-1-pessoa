import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IdleTimer } from "./idleTimer";

describe("IdleTimer (idle timeout LGPD — Story 1.3)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const make = (over = {}) => {
    const onWarn = vi.fn();
    const onTimeout = vi.fn();
    const onActive = vi.fn();
    const timer = new IdleTimer({
      idleMs: 30_000,
      warningMs: 5_000,
      onWarn,
      onTimeout,
      onActive,
      ...over,
    });
    return { timer, onWarn, onTimeout, onActive };
  };

  it("avisa em (idle - warning) e desloga em idle sem atividade", () => {
    const { timer, onWarn, onTimeout } = make();
    timer.start();

    vi.advanceTimersByTime(25_000); // janela de aviso
    expect(onWarn).toHaveBeenCalledTimes(1);
    expect(onTimeout).not.toHaveBeenCalled();

    vi.advanceTimersByTime(5_000); // esgota
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it("atividade reinicia a contagem e evita o timeout (fluxo ativo legítimo — AC2)", () => {
    const { timer, onWarn, onTimeout } = make();
    timer.start();

    vi.advanceTimersByTime(20_000);
    timer.activity(); // usuário interagiu (ex.: digitando um formulário longo)
    vi.advanceTimersByTime(20_000); // 40s desde o start, mas só 20s desde a atividade

    expect(onWarn).not.toHaveBeenCalled();
    expect(onTimeout).not.toHaveBeenCalled();
  });

  it("atividade após o aviso o esconde (onActive) e cancela o timeout", () => {
    const { timer, onWarn, onTimeout, onActive } = make();
    timer.start();

    vi.advanceTimersByTime(25_000);
    expect(onWarn).toHaveBeenCalledTimes(1);

    timer.activity();
    expect(onActive).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(5_000); // teria estourado sem a atividade
    expect(onTimeout).not.toHaveBeenCalled();
  });

  it("stop() cancela timers pendentes", () => {
    const { timer, onWarn, onTimeout } = make();
    timer.start();
    timer.stop();
    vi.advanceTimersByTime(60_000);
    expect(onWarn).not.toHaveBeenCalled();
    expect(onTimeout).not.toHaveBeenCalled();
  });
});
