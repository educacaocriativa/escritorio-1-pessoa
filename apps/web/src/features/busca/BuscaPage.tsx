import { useSearchParams } from "react-router-dom";

/** Esqueleto — a camada funda entra na Task 8. */
export default function BuscaPage() {
  const [params] = useSearchParams();
  return <p>{params.get("q") ?? ""}</p>;
}
