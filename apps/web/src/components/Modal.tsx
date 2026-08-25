import { X } from "lucide-react";
import type { ReactNode } from "react";

export default function Modal({
  title,
  open,
  onClose,
  children,
  footer,
  testId,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /**
   * `data-testid` na CAIXA do modal — cabeçalho e rodapé inclusive.
   *
   * ⚠️ Existe por causa da régua de 360px. Pôr o recorte no conteúdo (`children`) deixa título e
   * barra de ação FORA da varredura de `textoForaDaTela`, e foi exatamente assim que um título
   * comprido empurrando o "Fechar" 338px para fora da tela passou por uma medição que devolveu
   * lista vazia. Todo modal medido pela régua deve receber `testId` aqui, nunca num `<div>`
   * interno.
   */
  testId?: string;
  /**
   * Ação primária do modal. Vive numa barra `sticky bottom-0` DENTRO da caixa que rola, para que
   * ela nunca saia da tela enquanto o dono preenche o formulário. **Opcional**: modal que não
   * passa `footer` continua exatamente como era.
   *
   * ⚠️ Não é enfeite. Em 360×740 o formulário de conta bancária tem 1010px numa caixa de 629px —
   * sem esta barra o botão que efetiva a escolha "não sei o saldo" nasce 303px abaixo da borda da
   * tela e 467px abaixo da escolha, que é a forma do PR #56 (uma conta real foi marcada como paga
   * sem o dono conseguir ver o controle que a confirmava).
   */
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
    >
      <div
        data-testid={testId}
        // `campos-tocaveis` (`styles/index.css`): 44px de altura mínima em TODO campo de
        // digitação desta caixa — o `<input>` do `Field` abaixo e também os `<select>` e
        // `<input>` que cada tela escreve à mão ao lado dele. Medido em 22/08/2026: eram 38–40px
        // em 13 modais, 63 campos. É o mínimo do PR #56, onde um alvo pequeno demais fez uma
        // conta real ser marcada como paga sem o dono ver — num formulário, errar o alvo é
        // digitar no campo errado. Régua: `e2e/campo-modal-360.spec.ts`.
        className="campos-tocaveis max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          {/* `min-w-0 break-words`: o título é digitação livre — nome de contato, título de evento
              — e `name` aceita 255 chars no backend. Sem os dois, um nome colado sem espaço não
              tem onde quebrar, o `<h2>` cresce e empurra o "Fechar" para fora da tela: medido em
              698px numa viewport de 360. O `shrink-0` no botão é a outra metade — sem ele o
              flex o espreme antes de deixar o título quebrar. */}
          <h2 className="min-w-0 break-words text-lg font-bold text-neutral-800">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Fechar"
            className="-mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-pill text-neutral-400 hover:text-neutral-700"
          >
            <X size={20} />
          </button>
        </div>
        {children}
        {footer && (
          // `-mx-6 -mb-6` desfaz o `p-6` da caixa para a barra encostar nas bordas; o fundo opaco
          // é o que impede o conteúdo de aparecer por baixo dela enquanto rola.
          <div className="sticky bottom-0 -mx-6 -mb-6 mt-4 border-t border-neutral-100 bg-white px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * O campo de texto padrão dos modais — 84 usos em 14 telas.
 *
 * ⚠️ **A altura NÃO está nesta `className`, e isso é deliberado.** Ela vem da regra
 * `.campos-tocaveis` (`styles/index.css`), aplicada pela CAIXA do `Modal` acima. A razão é que
 * este componente nunca foi o problema inteiro: ao lado de quase todo `<Field>` há um `<select>`
 * escrito à mão com a mesma classe (`px-3 py-2 text-sm`) e a mesma altura errada, e há **três
 * cópias locais** deste componente que um conserto aqui não alcançaria
 * (`auth/LoginPage.tsx:203`, `funis/FunnelBuilderPage.tsx:736`,
 * `juridico/JuridicoWizardPage.tsx:178`). Pôr `min-h-11` aqui consertaria 84 campos e deixaria
 * outros ~35 em pé, com a aparência de dívida paga.
 *
 * Consequência prática: `<Field>` usado FORA de um `Modal` volta aos 38px. Quem o fizer precisa
 * declarar `campos-tocaveis` no contêiner do formulário — foi o que os três clones acima
 * receberam, e `e2e/campo-modal-360.spec.ts` mede os três, um a um.
 */
export function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
      />
    </label>
  );
}
