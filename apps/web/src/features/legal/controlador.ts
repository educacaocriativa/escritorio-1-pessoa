/**
 * Identificação de quem opera o e1p, em UM lugar só.
 *
 * Os dois documentos legais (`PrivacidadePage`, `TermosPage`) precisam repetir razão social,
 * CNPJ e contato. Duplicar isso em dois arquivos é como um documento fica desatualizado sem
 * ninguém perceber — e, num documento legal, divergir de si mesmo é pior do que estar velho.
 */
export const CONTROLADOR = {
  razaoSocial: "FLAVIO KATO LTDA",
  cnpj: "65.623.582/0001-08",
  email: "flaviokato76@gmail.com",
  produto: "e1p",
} as const;

/**
 * Data da última revisão dos documentos legais. Atualize AO MUDAR o texto de qualquer um dos
 * dois — a data é o que permite a uma pessoa saber se leu a versão vigente.
 */
export const VIGENCIA = "2 de setembro de 2026";
