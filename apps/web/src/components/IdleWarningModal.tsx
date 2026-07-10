import { IDLE_WARNING_MINUTES } from "../lib/idleTimer";
import Modal from "./Modal";

/**
 * Aviso de sessão prestes a expirar por inatividade (idle timeout LGPD — Story 1.3).
 * Reaproveita o `Modal` do design "Portal". Fechar (X/fundo) ou clicar em "Continuar conectado"
 * mantém a sessão; não fazer nada leva ao logout automático.
 */
export default function IdleWarningModal({
  open,
  onStay,
}: {
  open: boolean;
  onStay: () => void;
}) {
  return (
    <Modal title="Sessão prestes a expirar" open={open} onClose={onStay}>
      <p className="text-sm text-neutral-600">
        Por segurança (LGPD), sua sessão será encerrada em cerca de {IDLE_WARNING_MINUTES}{" "}
        {IDLE_WARNING_MINUTES === 1 ? "minuto" : "minutos"} por inatividade. Deseja continuar
        conectado?
      </p>
      <div className="mt-6 flex justify-end">
        <button
          type="button"
          onClick={onStay}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          Continuar conectado
        </button>
      </div>
    </Modal>
  );
}
