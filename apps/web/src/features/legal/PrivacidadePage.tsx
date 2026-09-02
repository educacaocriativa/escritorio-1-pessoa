import LegalLayout, { Lista, Secao, Tabela } from "./LegalLayout";
import { CONTROLADOR } from "./controlador";

/**
 * Política de Privacidade — página PÚBLICA em `/privacidade`.
 *
 * Existe por três exigências concretas, não por formalidade:
 *  1. LGPD (Lei 13.709/2018) art. 9º — informação clara sobre o tratamento.
 *  2. Google OAuth — a aba Branding da tela de consentimento exige a URL desta página para
 *     publicar o app; sem publicar, o refresh token morre a cada 7 dias.
 *  3. Google API Services User Data Policy — a seção "Uso Limitado" abaixo é literal e
 *     obrigatória para qualquer app que leia escopos de usuário do Google.
 *
 * O conteúdo descreve o que o sistema REALMENTE faz. Ao mudar coleta, integração ou retenção
 * no produto, este texto muda junto — descrever a mais é tão errado quanto omitir.
 */
export default function PrivacidadePage() {
  return (
    <LegalLayout
      titulo="Política de Privacidade"
      subtitulo={`Como o ${CONTROLADOR.produto} trata dados pessoais.`}
      outroDocumento={{ to: "/termos", label: "Termos de Serviço" }}
    >
      <Secao id="quem-somos" titulo="1. Quem trata seus dados">
        <p>
          O {CONTROLADOR.produto} é operado por <strong>{CONTROLADOR.razaoSocial}</strong>, inscrita
          no CNPJ sob o nº {CONTROLADOR.cnpj} ("nós"). Para qualquer assunto relativo a dados
          pessoais, incluindo o exercício dos seus direitos, o canal é{" "}
          <a className="text-primary-600 hover:underline" href={`mailto:${CONTROLADOR.email}`}>
            {CONTROLADOR.email}
          </a>
          , que também responde pelo encarregado de dados (DPO) previsto no art. 41 da LGPD.
        </p>
        <p>
          Esta política se aplica ao aplicativo web do {CONTROLADOR.produto} e a todas as suas
          integrações. Ao criar uma conta ou usar o sistema, você declara ter lido este documento.
        </p>
      </Secao>

      <Secao id="dois-papeis" titulo="2. Dois papéis diferentes, e isso importa">
        <p>
          O {CONTROLADOR.produto} é um sistema de gestão: você o usa para administrar o seu próprio
          negócio. Isso cria duas relações distintas, com responsabilidades distintas:
        </p>
        <Lista>
          <li>
            <strong>Sobre os seus dados de conta</strong> (o cadastro da sua empresa, o seu usuário,
            a cobrança da assinatura, os registros de acesso) somos <strong>controladores</strong>:
            decidimos por que e como tratá-los, nos termos desta política.
          </li>
          <li>
            <strong>Sobre os dados que você insere no sistema</strong> — seus clientes, seus
            contratos, suas conversas, seus lançamentos financeiros — somos{" "}
            <strong>operadores</strong>. Quem decide o que coletar, por quê e por quanto tempo é
            você, que é o controlador desses dados. Nós apenas os tratamos conforme as suas
            instruções, expressas pelo uso do sistema, e conforme os Termos de Serviço.
          </li>
        </Lista>
        <p>
          Na prática: se um cliente seu pedir a exclusão dos dados dele, o pedido é seu para
          atender, e o {CONTROLADOR.produto} lhe dá as ferramentas para isso. Se você pedir a
          exclusão da sua conta, o pedido é nosso para atender.
        </p>
      </Secao>

      <Secao id="dados-coletados" titulo="3. Que dados são tratados">
        <Tabela
          cabecalho={["Categoria", "Dados", "Origem"]}
          linhas={[
            [
              "Conta e empresa",
              "Razão social, CPF/CNPJ, fuso horário, nome, e-mail, senha (armazenada apenas como hash), telefone, endereço, perfil de acesso e módulos liberados.",
              "Você, ao contratar e ao cadastrar usuários.",
            ],
            [
              "Clientes e leads",
              "Nome, e-mail, telefone, CPF, data de nascimento, gênero, etiquetas, anotações e o histórico de interações que você registra.",
              "Você, ou formulários e páginas públicas que você mesmo publica.",
            ],
            [
              "Conversas de WhatsApp",
              "Mensagens enviadas e recebidas, número do contato, nome de exibição e anexos, quando você conecta um número ao sistema.",
              "A integração de WhatsApp que você ativar.",
            ],
            [
              "Agenda",
              "Compromissos, participantes, horários e links de reunião; o e-mail da conta Google conectada.",
              "Você e, se conectada, a sua conta Google.",
            ],
            [
              "Financeiro e documentos",
              "Contas a pagar e a receber, lançamentos, saldos, contratos, propostas, peças jurídicas e arquivos anexados.",
              "Você.",
            ],
            [
              "Registros técnicos",
              "Data e hora de acesso, ações relevantes em trilha de auditoria e registros de erro do servidor.",
              "Gerados automaticamente pelo uso.",
            ],
          ]}
        />
        <p>
          Não coletamos dados seus em sites de terceiros, não compramos listas e não fazemos
          rastreamento publicitário. O {CONTROLADOR.produto} não tem cookies de terceiros nem pixels
          de rede de anúncios.
        </p>
      </Secao>

      <Secao id="finalidades" titulo="4. Para que os dados são usados">
        <Lista>
          <li>
            <strong>Prestar o serviço</strong> — executar as funções que você aciona: cadastrar
            clientes, emitir cobranças, agendar compromissos, gerar documentos, trocar mensagens.
            Base legal: execução de contrato (art. 7º, V, da LGPD).
          </li>
          <li>
            <strong>Autenticar e proteger</strong> — verificar quem entra, encerrar sessões ociosas,
            manter trilha de auditoria e investigar uso indevido. Base legal: legítimo interesse e
            cumprimento de obrigação legal.
          </li>
          <li>
            <strong>Comunicar</strong> — avisos operacionais sobre a sua conta, o briefing diário
            que você habilitar e respostas de suporte. Base legal: execução de contrato.
          </li>
          <li>
            <strong>Cobrar a assinatura</strong> e cumprir obrigações fiscais e contábeis. Base
            legal: cumprimento de obrigação legal.
          </li>
        </Lista>
        <p>
          Não vendemos dados pessoais, não os cedemos para publicidade de terceiros e não os usamos
          para treinar modelos de inteligência artificial.
        </p>
      </Secao>

      <Secao id="ia" titulo="5. Inteligência artificial e anonimização">
        <p>
          Algumas funções do {CONTROLADOR.produto} usam modelos de IA da Anthropic (Claude) para
          redigir textos, resumir informações e responder perguntas sobre o seu negócio.
        </p>
        <p>
          Antes de qualquer texto sair do sistema em direção à IA, ele passa por um anonimizador que
          substitui CPF, CNPJ, e-mails, telefones e números de cartão por marcadores genéricos. A
          resposta volta com esses marcadores e os valores reais são reinseridos localmente, já
          dentro da nossa infraestrutura. O provedor de IA, portanto, não recebe esses
          identificadores.
        </p>
        <p>
          O conteúdo enviado à Anthropic não é usado para treinar os modelos dela. As respostas de
          IA são geradas automaticamente e podem conter erros: elas não substituem orientação
          jurídica, contábil ou financeira profissional. Ver a cláusula correspondente nos Termos de
          Serviço.
        </p>
      </Secao>

      <Secao id="google" titulo="6. Dados recebidos das APIs do Google">
        <p>
          Se você conectar a sua conta Google, o {CONTROLADOR.produto} solicita dois escopos, e
          apenas eles:
        </p>
        <Lista>
          <li>
            <code className="rounded bg-neutral-100 px-1">calendar.events</code> — para criar,
            alterar e cancelar no seu Google Agenda os compromissos que você marca no sistema,
            incluindo a geração do link do Google Meet, e para manter os dois lados sincronizados.
          </li>
          <li>
            <code className="rounded bg-neutral-100 px-1">userinfo.email</code> — apenas para exibir
            qual conta Google está conectada, de modo que você saiba onde os eventos estão sendo
            criados.
          </li>
        </Lista>
        <p>
          Não lemos seus e-mails, arquivos, contatos ou qualquer outro dado da sua conta Google.
          Você pode revogar o acesso a qualquer momento, dentro do {CONTROLADOR.produto} ou em{" "}
          <a
            className="text-primary-600 hover:underline"
            href="https://myaccount.google.com/permissions"
            target="_blank"
            rel="noreferrer"
          >
            myaccount.google.com/permissions
          </a>
          . Ao revogar, apagamos as credenciais armazenadas e a sincronização para de funcionar; os
          eventos já criados permanecem onde estão.
        </p>
        <p className="rounded-lg bg-neutral-100 p-3">
          <strong>Uso Limitado.</strong> O uso e a transferência, pelo {CONTROLADOR.produto}, de
          informações recebidas das APIs do Google obedecerão à{" "}
          <a
            className="text-primary-600 hover:underline"
            href="https://developers.google.com/terms/api-services-user-data-policy"
            target="_blank"
            rel="noreferrer"
          >
            Política de Dados do Usuário dos Serviços de API do Google
          </a>
          , incluindo os requisitos de Uso Limitado.
        </p>
      </Secao>

      <Secao id="compartilhamento" titulo="7. Com quem os dados são compartilhados">
        <p>
          Compartilhamos dados apenas com os prestadores necessários para o serviço funcionar, cada
          um limitado ao que a sua função exige:
        </p>
        <Tabela
          cabecalho={["Prestador", "Para quê", "Onde"]}
          linhas={[
            [
              "Amazon Web Services (AWS)",
              "Hospedagem da aplicação, do banco de dados e dos arquivos anexados.",
              "Brasil (região de São Paulo)",
            ],
            [
              "Anthropic",
              "Processamento das funções de IA, com os dados já anonimizados.",
              "Estados Unidos",
            ],
            [
              "Google",
              "Sincronização do Google Agenda e do Google Meet, quando você conecta a conta.",
              "Estados Unidos",
            ],
            [
              "Meta (WhatsApp Business Platform)",
              "Envio e recebimento de mensagens, quando você usa a integração oficial.",
              "Estados Unidos",
            ],
            [
              "Asaas",
              "Emissão de boletos e Pix das suas cobranças, quando o gateway está habilitado.",
              "Brasil",
            ],
            [
              "Provedor de e-mail transacional",
              "Envio dos e-mails do sistema, como recuperação de senha.",
              "Brasil / Estados Unidos",
            ],
          ]}
        />
        <p>
          As transferências internacionais acima ocorrem com base em cláusulas contratuais e nas
          demais garantias exigidas pelos arts. 33 e seguintes da LGPD. Também podemos divulgar
          dados diante de ordem judicial ou requisição de autoridade competente e, nesse caso,
          avisaremos você sempre que a lei permitir.
        </p>
      </Secao>

      <Secao id="seguranca" titulo="8. Como os dados são protegidos">
        <Lista>
          <li>Todo o tráfego entre o seu navegador e o sistema é cifrado por HTTPS/TLS.</li>
          <li>Senhas são guardadas apenas como hash; nem nós conseguimos lê-las.</li>
          <li>
            O banco de dados aplica isolamento por assinante em nível de linha (Row Level Security):
            os dados de uma empresa são inalcançáveis a partir da sessão de outra por decisão do
            próprio banco, e não apenas por filtro da aplicação.
          </li>
          <li>Sessões inativas são encerradas automaticamente após 30 minutos.</li>
          <li>Acessos e ações sensíveis ficam registrados em trilha de auditoria.</li>
          <li>Backups automáticos são mantidos, com cópia fora do servidor de produção.</li>
        </Lista>
        <p>
          Nenhum sistema é imune a incidentes. Se ocorrer um incidente de segurança com risco
          relevante aos seus dados, comunicaremos você e a Autoridade Nacional de Proteção de Dados
          (ANPD), conforme o art. 48 da LGPD.
        </p>
      </Secao>

      <Secao id="retencao" titulo="9. Por quanto tempo os dados ficam guardados">
        <Lista>
          <li>
            <strong>Enquanto a sua conta existir</strong>, os dados do negócio permanecem
            disponíveis para você.
          </li>
          <li>
            <strong>Após o encerramento da conta</strong>, os dados são excluídos em até 30 dias,
            salvo o que precisarmos reter por obrigação legal — registros fiscais e o registro de
            acessos exigido pelo art. 15 do Marco Civil da Internet, mantido por 6 meses.
          </li>
          <li>
            <strong>Backups</strong> têm ciclo próprio: até 7 dias no servidor e até 30 dias na
            cópia externa. Um dado excluído desaparece das cópias ao fim desse ciclo.
          </li>
        </Lista>
      </Secao>

      <Secao id="direitos" titulo="10. Seus direitos">
        <p>Pelo art. 18 da LGPD, você pode a qualquer momento pedir:</p>
        <Lista>
          <li>confirmação de que tratamos seus dados, e acesso a eles;</li>
          <li>correção de dados incompletos, inexatos ou desatualizados;</li>
          <li>anonimização, bloqueio ou eliminação de dados desnecessários ou excessivos;</li>
          <li>portabilidade dos dados a outro fornecedor;</li>
          <li>eliminação dos dados tratados com base no seu consentimento;</li>
          <li>informação sobre com quem compartilhamos seus dados;</li>
          <li>revogação do consentimento.</li>
        </Lista>
        <p>
          Basta escrever para{" "}
          <a className="text-primary-600 hover:underline" href={`mailto:${CONTROLADOR.email}`}>
            {CONTROLADOR.email}
          </a>
          . Respondemos em até 15 dias. Podemos pedir uma confirmação de identidade antes de
          atender — é uma proteção contra alguém se passar por você.
        </p>
        <p>
          Se o seu pedido se referir a dados que uma empresa assinante inseriu no{" "}
          {CONTROLADOR.produto} sobre você (por exemplo, você é cliente de quem usa o sistema),
          encaminharemos o pedido a essa empresa, que é a controladora daqueles dados.
        </p>
      </Secao>

      <Secao id="cookies" titulo="11. Cookies e armazenamento no navegador">
        <p>
          Usamos armazenamento local do navegador apenas para o essencial: manter você autenticado
          entre telas e guardar preferências de exibição. Não há cookies de publicidade, de análise
          comportamental ou de terceiros. Limpar os dados do site desconecta a sua sessão e não
          apaga nada do seu negócio.
        </p>
      </Secao>

      <Secao id="menores" titulo="12. Crianças e adolescentes">
        <p>
          O {CONTROLADOR.produto} é uma ferramenta profissional e não se destina a menores de 18
          anos. Não coletamos conscientemente dados de crianças ou adolescentes como titulares de
          conta. Se identificarmos um cadastro nessa condição, ele será removido.
        </p>
      </Secao>

      <Secao id="mudancas" titulo="13. Mudanças nesta política">
        <p>
          Podemos atualizar este documento para refletir mudanças no sistema ou na legislação. A
          data de última atualização, no topo da página, indica a versão vigente. Se a mudança
          alterar de forma relevante como tratamos seus dados, avisaremos por e-mail ou dentro do
          sistema antes de ela passar a valer.
        </p>
      </Secao>

      <Secao id="foro" titulo="14. Lei aplicável">
        <p>
          Esta política é regida pela lei brasileira. Fica eleito o foro da comarca do domicílio do
          titular para dirimir as controvérsias dela decorrentes.
        </p>
      </Secao>
    </LegalLayout>
  );
}
