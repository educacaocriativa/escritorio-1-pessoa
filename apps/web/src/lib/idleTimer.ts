/**
 * Idle timeout LGPD (Story 1.3).
 *
 * Camada de UX no cliente: avisa o usuário ANTES do logout por inatividade e desliza a sessão
 * no backend (`POST /auth/refresh`) enquanto há atividade real. A EXPIRAÇÃO em si é garantida
 * pelo backend (o access token expira por inatividade e o interceptor 401 desloga) — este timer
 * é a experiência amigável em cima disso. Se cliente e backend divergirem, o backend ainda
 * protege via 401 (fail-closed).
 *
 * A classe é pura (timers injetáveis) para ser testável sem DOM.
 */

/**
 * Minutos de inatividade até o logout. DEVE espelhar `session_idle_timeout_minutes` do backend
 * (apps/api/app/config.py). O backend é a fonte de verdade da expiração; este número controla
 * apenas o momento do AVISO/logout do cliente.
 */
export const IDLE_TIMEOUT_MINUTES = 30;

/** Antecedência (min) com que o aviso aparece antes do logout. */
export const IDLE_WARNING_MINUTES = 1;

/**
 * Intervalo mínimo (min) entre chamadas a `/auth/refresh`. Evita reemitir a cada mousemove —
 * mantém a sessão viva durante uso ativo sem gerar carga desnecessária na API (IV3).
 */
export const IDLE_REFRESH_INTERVAL_MINUTES = 5;

type TimerId = ReturnType<typeof setTimeout>;

export interface IdleTimerOptions {
  /** Duração total da janela de inatividade em ms. */
  idleMs: number;
  /** Quanto antes do timeout mostrar o aviso, em ms. */
  warningMs: number;
  /** Chamado ao entrar na janela de aviso (idleMs - warningMs sem atividade). */
  onWarn: () => void;
  /** Chamado quando a janela total esgota sem atividade. */
  onTimeout: () => void;
  /** Chamado quando há atividade APÓS um aviso ter sido exibido (para escondê-lo). */
  onActive?: () => void;
  /** Injeção para testes. */
  setTimer?: (cb: () => void, ms: number) => TimerId;
  clearTimer?: (id: TimerId) => void;
}

export class IdleTimer {
  private readonly idleMs: number;
  private readonly warningMs: number;
  private readonly onWarn: () => void;
  private readonly onTimeout: () => void;
  private readonly onActive: () => void;
  private readonly setTimer: (cb: () => void, ms: number) => TimerId;
  private readonly clearTimer: (id: TimerId) => void;

  private warnId: TimerId | null = null;
  private timeoutId: TimerId | null = null;
  private warned = false;

  constructor(opts: IdleTimerOptions) {
    this.idleMs = opts.idleMs;
    this.warningMs = Math.min(opts.warningMs, opts.idleMs);
    this.onWarn = opts.onWarn;
    this.onTimeout = opts.onTimeout;
    this.onActive = opts.onActive ?? (() => {});
    this.setTimer = opts.setTimer ?? ((cb, ms) => setTimeout(cb, ms));
    this.clearTimer = opts.clearTimer ?? ((id) => clearTimeout(id));
  }

  /** Inicia a contagem. */
  start(): void {
    this.schedule();
  }

  /** Para a contagem e limpa os timers pendentes. */
  stop(): void {
    this.clear();
    this.warned = false;
  }

  /**
   * Registra atividade do usuário: reinicia a contagem. Se um aviso estava visível, dispara
   * `onActive` para escondê-lo.
   */
  activity(): void {
    if (this.warned) {
      this.warned = false;
      this.onActive();
    }
    this.schedule();
  }

  private schedule(): void {
    this.clear();
    this.warnId = this.setTimer(() => {
      this.warned = true;
      this.onWarn();
    }, this.idleMs - this.warningMs);
    this.timeoutId = this.setTimer(() => {
      this.onTimeout();
    }, this.idleMs);
  }

  private clear(): void {
    if (this.warnId !== null) this.clearTimer(this.warnId);
    if (this.timeoutId !== null) this.clearTimer(this.timeoutId);
    this.warnId = null;
    this.timeoutId = null;
  }
}
