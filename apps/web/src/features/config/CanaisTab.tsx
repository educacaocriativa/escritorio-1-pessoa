import CelularSection from "./CelularSection";
import WhatsappSection from "./WhatsappSection";

/** Aba "Canais": por onde a mensagem entra e sai — WhatsApp e o celular do dono. */
export default function CanaisTab() {
  return (
    <div className="space-y-6">
      <WhatsappSection />
      <CelularSection />
    </div>
  );
}
