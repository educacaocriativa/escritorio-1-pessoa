import type { Product, StockItem, StockSummary } from "@e1p/shared-types";
import { AlertTriangle, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function EstoquePage() {
  const empty: StockSummary = { item_count: 0, total_value_cents: 0, low_stock_count: 0 };
  const [summary, setSummary] = useState<StockSummary>(empty);
  const [items, setItems] = useState<StockItem[]>([]);
  const [newOpen, setNewOpen] = useState(false);
  const [adjust, setAdjust] = useState<StockItem | null>(null);

  const load = useCallback(async () => {
    const [s, i] = await Promise.all([
      api.get<StockSummary>("/stock/summary"),
      api.get<StockItem[]>("/stock/items"),
    ]);
    setSummary(s.data);
    setItems(i.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo item", useCallback(() => setNewOpen(true), []));

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Estoque</p>
        <h1 className="text-2xl font-bold text-neutral-800">Controle de Estoque</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Itens ativos" value={String(summary.item_count)} tone="text-neutral-700" />
        <Stat label="Valor em estoque" value={brl(summary.total_value_cents)} tone="text-accent-700" />
        <Stat
          label="Estoque baixo"
          value={String(summary.low_stock_count)}
          tone={summary.low_stock_count > 0 ? "text-danger" : "text-neutral-700"}
        />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {items.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhum item. Clique em "Novo item".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Item</th>
                <th className="px-4 py-3 font-medium">Quantidade</th>
                <th className="px-4 py-3 font-medium">Custo un.</th>
                <th className="px-4 py-3 font-medium">Valor</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className="border-b border-neutral-50 last:border-0">
                  <td className="px-4 py-3">
                    <span className="font-medium text-neutral-800">{i.name}</span>
                    {i.sku && <span className="ml-2 text-xs text-neutral-400">{i.sku}</span>}
                    {i.product_id && (
                      <span className="ml-2 rounded-pill bg-primary-50 px-1.5 text-[10px] text-primary-700">
                        ligado a produto
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-medium tabular-nums ${i.low ? "text-danger" : "text-neutral-700"}`}>
                      {i.quantity} {i.unit}
                    </span>
                    {i.low && (
                      <span className="ml-2 inline-flex items-center gap-1 text-xs text-danger">
                        <AlertTriangle size={12} /> mín {i.min_quantity}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-neutral-600">{brl(i.unit_cost_cents)}</td>
                  <td className="px-4 py-3 font-medium tabular-nums">{brl(i.value_cents)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setAdjust(i)}
                      className="rounded-pill bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-200"
                    >
                      Movimentar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewItemModal open={newOpen} onClose={() => setNewOpen(false)} onCreated={load} />
      {adjust && (
        <AdjustModal
          item={adjust}
          onClose={() => setAdjust(null)}
          onDone={() => {
            setAdjust(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function NewItemModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [quantity, setQuantity] = useState("0");
  const [cost, setCost] = useState("");
  const [min, setMin] = useState("0");
  const [unit, setUnit] = useState("un");
  const [productId, setProductId] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) api.get<Product[]>("/products").then(({ data }) => setProducts(data));
  }, [open]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post("/stock/items", {
        name,
        sku,
        unit,
        product_id: productId || null,
        quantity: parseInt(quantity, 10) || 0,
        min_quantity: parseInt(min, 10) || 0,
        unit_cost_cents: Math.round(parseFloat(cost.replace(",", ".") || "0") * 100),
      });
      onCreated();
      onClose();
      setName("");
      setSku("");
      setQuantity("0");
      setCost("");
      setMin("0");
      setProductId("");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Novo item de estoque" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome" value={name} onChange={setName} />
        <div className="flex gap-2">
          <Field label="SKU (opcional)" value={sku} onChange={setSku} />
          <Field label="Unidade" value={unit} onChange={setUnit} />
        </div>
        <div className="flex gap-2">
          <Field label="Quantidade inicial" value={quantity} onChange={setQuantity} />
          <Field label="Estoque mínimo" value={min} onChange={setMin} />
        </div>
        <Field label="Custo unitário (R$)" value={cost} onChange={setCost} placeholder="0,00" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Ligar a um produto (baixa automática na venda)
          </span>
          <select
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="">Não ligar</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !name}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar item"}
        </button>
      </div>
    </Modal>
  );
}

function AdjustModal({
  item,
  onClose,
  onDone,
}: {
  item: StockItem;
  onClose: () => void;
  onDone: () => void;
}) {
  const [qty, setQty] = useState("1");
  const [direction, setDirection] = useState<1 | -1>(1);
  const [reason, setReason] = useState("purchase");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const amount = (parseInt(qty, 10) || 0) * direction;
      await api.post(`/stock/items/${item.id}/adjust`, { delta: amount, reason, note });
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Movimentar: ${item.name}`} open onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-neutral-500">
          Atual: <b>{item.quantity} {item.unit}</b>
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => {
              setDirection(1);
              setReason("purchase");
            }}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-pill py-2 text-sm font-semibold ${direction === 1 ? "bg-accent-50 text-accent-700" : "bg-neutral-100 text-neutral-500"}`}
          >
            <Plus size={14} /> Entrada
          </button>
          <button
            onClick={() => {
              setDirection(-1);
              setReason("adjust");
            }}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-pill py-2 text-sm font-semibold ${direction === -1 ? "bg-red-50 text-danger" : "bg-neutral-100 text-neutral-500"}`}
          >
            <Minus size={14} /> Saída
          </button>
        </div>
        <Field label="Quantidade" value={qty} onChange={setQty} />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Motivo</span>
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="purchase">Compra/Reposição</option>
            <option value="adjust">Ajuste</option>
            <option value="loss">Perda/Quebra</option>
          </select>
        </label>
        <Field label="Observação (opcional)" value={note} onChange={setNote} />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : direction === 1 ? "Dar entrada" : "Dar baixa"}
        </button>
      </div>
    </Modal>
  );
}
