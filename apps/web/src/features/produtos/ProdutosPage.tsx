import type { Coupon, Enrollment, Product } from "@e1p/shared-types";
import { Copy } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

type Tab = "produtos" | "cupons" | "compradores";
const TAB_LABELS: Record<Tab, string> = {
  produtos: "Produtos",
  cupons: "Cupons",
  compradores: "Compradores",
};

const KINDS = [
  ["membership", "Área de membros"],
  ["digital", "Infoproduto"],
  ["physical", "Produto físico"],
] as const;
const kindLabel = (k: string) => KINDS.find(([v]) => v === k)?.[1] ?? k;

export default function ProdutosPage() {
  const [tab, setTab] = useState<Tab>("produtos");
  const [products, setProducts] = useState<Product[]>([]);
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [alunos, setAlunos] = useState<Enrollment[]>([]);
  const [productModal, setProductModal] = useState(false);
  const [couponModal, setCouponModal] = useState(false);
  const [sellFor, setSellFor] = useState<Product | null>(null);

  const load = useCallback(async () => {
    const [p, c, e] = await Promise.all([
      api.get<Product[]>("/products"),
      api.get<Coupon[]>("/products/coupons"),
      api.get<Enrollment[]>("/products/enrollments"),
    ]);
    setProducts(p.data);
    setCoupons(c.data);
    setAlunos(e.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const actionLabel = tab === "cupons" ? "Novo cupom" : "Novo produto";
  usePrimaryAction(
    actionLabel,
    useCallback(() => {
      if (tab === "cupons") setCouponModal(true);
      else setProductModal(true);
    }, [tab]),
  );

  async function toggleCoupon(id: string) {
    await api.post(`/products/coupons/${id}/toggle`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Produtos</p>
        <h1 className="text-2xl font-bold text-neutral-800">Produtos</h1>
      </div>

      <div className="flex gap-1 rounded-pill bg-neutral-100 p-1 text-sm">
        {(["produtos", "cupons", "compradores"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-pill px-4 py-1.5 font-medium transition ${
              tab === t ? "bg-white text-primary-700 shadow-sm" : "text-neutral-500"
            }`}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {tab === "produtos" && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {products.length === 0 ? (
            <p className="text-sm text-neutral-400">Nenhum produto ainda.</p>
          ) : (
            products.map((p) => (
              <div key={p.id} className="rounded-2xl bg-white p-5 shadow-sm">
                <div className="mb-2 flex items-start justify-between">
                  <div>
                    <p className="font-semibold text-neutral-800">{p.name}</p>
                    <p className="text-xs text-neutral-400">{kindLabel(p.kind)}</p>
                  </div>
                  {!p.active && (
                    <span className="rounded-pill bg-neutral-100 px-2 text-xs text-neutral-500">
                      Inativo
                    </span>
                  )}
                </div>
                <p className="text-xl font-bold text-neutral-800">{brl(p.price_cents)}</p>
                <p className="mt-1 text-xs text-neutral-400">
                  {p.students} comprador(es){p.stock != null && ` · estoque ${p.stock}`}
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={() => setSellFor(p)}
                    className="rounded-pill bg-accent-400 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-500"
                  >
                    Vender
                  </button>
                  <button
                    onClick={() => navigator.clipboard?.writeText(p.checkout_url)}
                    title="Copiar link de checkout"
                    className="flex items-center gap-1 rounded-pill bg-neutral-100 px-3 py-1.5 text-xs text-neutral-500 hover:text-neutral-700"
                  >
                    <Copy size={12} /> Link
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {tab === "cupons" && (
        <Card>
          {coupons.length === 0 ? (
            <Empty text="Nenhum cupom." />
          ) : (
            <table className="w-full text-sm">
              <Head cols={["Código", "Desconto", "Usos", "Status", ""]} />
              <tbody>
                {coupons.map((c) => (
                  <tr key={c.id} className="border-b border-neutral-50 last:border-0">
                    <td className="px-4 py-3 font-mono font-medium text-neutral-800">{c.code}</td>
                    <td className="px-4 py-3 text-neutral-600">
                      {c.discount_type === "percent"
                        ? `${c.discount_value}%`
                        : brl(c.discount_value)}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-neutral-500">
                      {c.uses}
                      {c.max_uses != null && `/${c.max_uses}`}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-pill px-2 py-0.5 text-xs ${
                          c.active ? "bg-accent-50 text-accent-700" : "bg-neutral-100 text-neutral-500"
                        }`}
                      >
                        {c.active ? "Ativo" : "Inativo"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => toggleCoupon(c.id)}
                        className="text-xs font-medium text-primary-600 hover:underline"
                      >
                        {c.active ? "Desativar" : "Ativar"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {tab === "compradores" && (
        <Card>
          {alunos.length === 0 ? (
            <Empty text="Nenhum comprador ainda." />
          ) : (
            <table className="w-full text-sm">
              <Head cols={["Comprador", "Produto", "Valor", "Status"]} />
              <tbody>
                {alunos.map((a) => (
                  <tr key={a.id} className="border-b border-neutral-50 last:border-0">
                    <td className="px-4 py-3">
                      <span className="font-medium text-neutral-800">{a.name}</span>
                      {a.email && <span className="block text-xs text-neutral-400">{a.email}</span>}
                    </td>
                    <td className="px-4 py-3 text-neutral-600">{a.product_name ?? "—"}</td>
                    <td className="px-4 py-3 tabular-nums">{brl(a.amount_cents)}</td>
                    <td className="px-4 py-3">
                      <span className="rounded-pill bg-accent-50 px-2 py-0.5 text-xs text-accent-700">
                        {a.status === "active" ? "Ativo" : a.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      <ProductModal open={productModal} onClose={() => setProductModal(false)} onCreated={load} />
      <CouponModal
        open={couponModal}
        products={products}
        onClose={() => setCouponModal(false)}
        onCreated={load}
      />
      {sellFor && (
        <SellModal product={sellFor} onClose={() => setSellFor(null)} onSold={load} />
      )}
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="overflow-hidden rounded-2xl bg-white shadow-sm">{children}</div>;
}
function Empty({ text }: { text: string }) {
  return <p className="p-8 text-center text-sm text-neutral-400">{text}</p>;
}
function Head({ cols }: { cols: string[] }) {
  return (
    <thead>
      <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
        {cols.map((c, i) => (
          <th key={i} className={`px-4 py-3 font-medium ${i === cols.length - 1 ? "text-right" : ""}`}>
            {c}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function ProductModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("membership");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post("/products", {
        name,
        kind,
        price_cents: Math.round(parseFloat(value.replace(",", ".")) * 100),
        description,
      });
      onCreated();
      setName("");
      setValue("");
      setDescription("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Novo produto" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome" value={name} onChange={setName} placeholder="Curso de ..." />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            {KINDS.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <Field label="Preço (R$)" value={value} onChange={setValue} placeholder="197,00" />
        <Field label="Descrição" value={description} onChange={setDescription} />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !name || !value} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Salvando..." : "Criar produto"}
        </button>
      </div>
    </Modal>
  );
}

function CouponModal({
  open,
  products,
  onClose,
  onCreated,
}: {
  open: boolean;
  products: Product[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [code, setCode] = useState("");
  const [type, setType] = useState("percent");
  const [value, setValue] = useState("");
  const [productId, setProductId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const discount_value =
        type === "percent"
          ? parseInt(value, 10)
          : Math.round(parseFloat(value.replace(",", ".")) * 100);
      await api.post("/products/coupons", {
        code,
        discount_type: type,
        discount_value,
        product_id: productId || null,
      });
      onCreated();
      setCode("");
      setValue("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Novo cupom" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Código" value={code} onChange={setCode} placeholder="PROMO10" />
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
            <select value={type} onChange={(e) => setType(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              <option value="percent">Percentual (%)</option>
              <option value="fixed">Valor fixo (R$)</option>
            </select>
          </label>
          <Field label={type === "percent" ? "Desconto (%)" : "Desconto (R$)"} value={value} onChange={setValue} />
        </div>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Produto (opcional)</span>
          <select value={productId} onChange={(e) => setProductId(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            <option value="">Qualquer produto</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !code || !value} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Salvando..." : "Criar cupom"}
        </button>
      </div>
    </Modal>
  );
}

function SellModal({
  product,
  onClose,
  onSold,
}: {
  product: Product;
  onClose: () => void;
  onSold: () => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [method, setMethod] = useState("pix");
  const [coupon, setCoupon] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post(`/products/${product.id}/sell`, {
        name,
        email: email || null,
        method,
        coupon_code: coupon || null,
      });
      onSold();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Vender: ${product.name}`} open onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-neutral-500">Preço: {brl(product.price_cents)}</p>
        <Field label="Nome do comprador" value={name} onChange={setName} />
        <Field label="E-mail" type="email" value={email} onChange={setEmail} />
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Forma</span>
            <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              <option value="pix">Pix</option>
              <option value="card">Cartão</option>
              <option value="boleto">Boleto</option>
            </select>
          </label>
          <Field label="Cupom (opcional)" value={coupon} onChange={setCoupon} />
        </div>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !name} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Processando..." : "Confirmar venda"}
        </button>
      </div>
    </Modal>
  );
}
