import { Link } from "react-router-dom";
import LegalLayout, { Lista, Secao } from "./LegalLayout";
import { CONTROLADOR } from "./controlador";

/**
 * Termos de Serviço — página PÚBLICA em `/termos`.
 *
 * O Google não exige este documento para publicar o app OAuth (só a Política de Privacidade é
 * obrigatória lá). Ele existe pelo motivo próprio: o e1p gera peças jurídicas, projeções
 * financeiras e mensagens em nome do assinante, e é preciso estar escrito de quem é cada
 * responsabilidade — especialmente a de que a IA não substitui profissional habilitado.
 */
export default function TermosPage() {
  return (
    <LegalLayout
      titulo="Termos de Serviço"
      subtitulo={`Condições de uso do ${CONTROLADOR.produto}.`}
      outroDocumento={{ to: "/privacidade", label: "Política de Privacidade" }}
    >
      <Secao id="objeto" titulo="1. Objeto e aceitação">
        <p>
          Estes termos regem o uso do {CONTROLADOR.produto}, sistema de gestão para negócios
          conduzidos por uma pessoa, fornecido por <strong>{CONTROLADOR.razaoSocial}</strong>, CNPJ
          nº {CONTROLADOR.cnpj} ("nós"). Ao criar uma conta ou usar o sistema, você ("assinante")
          concorda com estas condições e com a{" "}
          <Link className="text-primary-600 hover:underline" to="/privacidade">
            Política de Privacidade
          </Link>
          , que é parte integrante deste documento.
        </p>
        <p>Se você não concorda com algum ponto, não use o sistema.</p>
      </Secao>

      <Secao id="conta" titulo="2. Conta de acesso">
        <Lista>
          <li>
            O acesso é nominal e destinado a maiores de 18 anos, com capacidade civil, agindo em
            nome próprio ou de pessoa jurídica que representem.
          </li>
          <li>
            Você é responsável pela guarda da sua senha e por tudo que for feito com as suas
            credenciais. Suspeitando de acesso indevido, troque a senha e avise-nos.
          </li>
          <li>
            Ao cadastrar sub-usuários, você responde pelas ações deles no sistema e pelos módulos
            que lhes libera.
          </li>
          <li>Os dados de cadastro devem ser verdadeiros e mantidos atualizados.</li>
        </Lista>
      </Secao>

      <Secao id="licenca" titulo="3. Licença de uso">
        <p>
          Enquanto a assinatura estiver ativa e adimplente, concedemos a você uma licença pessoal,
          intransferível, não exclusiva e revogável para usar o {CONTROLADOR.produto} conforme estes
          termos. A licença não transfere propriedade sobre o software.
        </p>
      </Secao>

      <Secao id="seus-dados" titulo="4. Os dados que você insere continuam seus">
        <p>
          O conteúdo que você cadastra no sistema — clientes, contratos, documentos, lançamentos,
          mensagens, arquivos — é seu. Não reivindicamos propriedade sobre ele e não o usamos para
          finalidade alheia à prestação do serviço. Nós o tratamos como operadores, sob as suas
          instruções, conforme a seção 2 da Política de Privacidade.
        </p>
        <p>
          Em contrapartida, <strong>você é o controlador desses dados</strong> perante a LGPD. Cabe
          a você ter base legal para coletar e tratar os dados dos seus clientes, atender aos
          pedidos que eles fizerem e informá-los sobre o tratamento. Nós ajudamos com as
          ferramentas; a responsabilidade legal é sua.
        </p>
      </Secao>

      <Secao id="uso-aceitavel" titulo="5. Uso aceitável">
        <p>Ao usar o {CONTROLADOR.produto}, você se compromete a não:</p>
        <Lista>
          <li>
            enviar mensagens não solicitadas em massa, spam ou qualquer comunicação que viole as
            políticas do WhatsApp, da Meta ou a legislação aplicável;
          </li>
          <li>
            tratar dados de terceiros sem base legal, nem inserir no sistema dados sensíveis para
            os quais você não tenha respaldo;
          </li>
          <li>
            usar o sistema para atividade ilícita, fraudulenta, difamatória ou que viole direitos de
            terceiros;
          </li>
          <li>
            tentar burlar limites técnicos, acessar dados de outros assinantes, aplicar engenharia
            reversa, revender ou sublicenciar o acesso;
          </li>
          <li>
            sobrecarregar deliberadamente a infraestrutura, por automação abusiva ou de outro modo.
          </li>
        </Lista>
        <p>
          A violação destes itens autoriza a suspensão imediata da conta, com aviso sempre que for
          possível dar aviso.
        </p>
      </Secao>

      <Secao id="ia" titulo="6. Conteúdo gerado por inteligência artificial">
        <p>
          O {CONTROLADOR.produto} usa IA para redigir textos, sugerir análises, produzir minutas de
          documentos e responder perguntas sobre o seu negócio. Esse conteúdo é gerado
          automaticamente e <strong>pode conter erros, omissões ou imprecisões</strong>.
        </p>
        <p>
          Nada do que a IA produz constitui aconselhamento jurídico, contábil, tributário, financeiro
          ou de investimentos. Minutas de contratos, peças jurídicas, projeções de caixa e
          diagnósticos são <strong>ponto de partida</strong>, não parecer profissional. Antes de
          assinar, enviar ou decidir com base nesse material, revise-o e, quando o caso exigir,
          consulte um profissional habilitado.
        </p>
        <p>
          A revisão do conteúdo antes do uso é responsabilidade sua, e não respondemos por decisões
          tomadas com base em saídas de IA não revisadas.
        </p>
      </Secao>

      <Secao id="integracoes" titulo="7. Integrações com terceiros">
        <p>
          O sistema pode se conectar a serviços de terceiros — Google Agenda e Google Meet, WhatsApp,
          gateway de pagamento, entre outros. Essas conexões são opcionais e você as ativa. Ao
          ativá-las, você fica também sujeito aos termos do serviço correspondente, e a
          disponibilidade e o comportamento deles não estão sob o nosso controle.
        </p>
        <p>
          Você pode revogar qualquer integração a qualquer momento; a funcionalidade que dependia
          dela deixa de operar, sem prejuízo do restante do sistema.
        </p>
      </Secao>

      <Secao id="disponibilidade" titulo="8. Disponibilidade, manutenção e backups">
        <Lista>
          <li>
            Trabalhamos para manter o serviço disponível de forma contínua, mas ele é fornecido
            "como está", sem garantia de operação ininterrupta ou livre de falhas.
          </li>
          <li>
            Podemos realizar manutenções programadas, avisando com antecedência razoável quando
            houver indisponibilidade prevista, e manutenções emergenciais sem aviso prévio.
          </li>
          <li>
            Mantemos backups automáticos com cópia externa, conforme a seção 9 da Política de
            Privacidade. Backup é medida de continuidade do serviço, não substituto de exportação
            própria: você pode exportar seus dados a qualquer momento e é prudente fazê-lo.
          </li>
          <li>
            Podemos alterar, adicionar ou descontinuar funcionalidades. Se uma mudança reduzir de
            forma relevante o que você contratou, avisaremos com antecedência.
          </li>
        </Lista>
      </Secao>

      <Secao id="pagamento" titulo="9. Assinatura, pagamento e cancelamento">
        <Lista>
          <li>
            Os valores, a periodicidade e a forma de pagamento são os informados no ato da
            contratação. Reajustes serão comunicados com pelo menos 30 dias de antecedência e valem
            para o ciclo seguinte.
          </li>
          <li>
            O atraso no pagamento pode levar à suspensão do acesso após aviso. Persistindo a
            inadimplência, a conta pode ser encerrada nos termos da seção 12.
          </li>
          <li>
            Você pode cancelar a assinatura quando quiser. O cancelamento vale para o fim do ciclo
            já pago, sem devolução proporcional, salvo o caso do item seguinte.
          </li>
          <li>
            Sendo você consumidor, tem direito de arrependimento em até 7 dias da contratação, com
            devolução integral, na forma do art. 49 do Código de Defesa do Consumidor.
          </li>
        </Lista>
      </Secao>

      <Secao id="propriedade" titulo="10. Propriedade intelectual">
        <p>
          O software, a marca, a interface, a documentação e os demais elementos do
          {" "}{CONTROLADOR.produto} pertencem a {CONTROLADOR.razaoSocial}. Estes termos não
          transferem nenhum desses direitos. Sugestões e comentários que você nos enviar podem ser
          usados para melhorar o produto, sem que isso gere obrigação de contrapartida.
        </p>
      </Secao>

      <Secao id="responsabilidade" titulo="11. Limitação de responsabilidade">
        <p>
          Na máxima extensão permitida pela lei, não respondemos por lucros cessantes, perda de
          oportunidade de negócio, danos indiretos ou por consequências de decisões que você tomar
          com base em informações do sistema, inclusive as geradas por IA.
        </p>
        <p>
          Nossa responsabilidade total, em qualquer hipótese, fica limitada ao valor que você pagou
          pela assinatura nos 12 meses anteriores ao evento que originou a reclamação.
        </p>
        <p>
          Esta limitação não afasta as garantias que a legislação consumerista brasileira torna
          inafastáveis nem responsabilidade por dolo.
        </p>
      </Secao>

      <Secao id="encerramento" titulo="12. Encerramento da conta">
        <p>
          Você pode encerrar a conta a qualquer momento. Nós podemos encerrá-la em caso de violação
          destes termos, inadimplência persistente ou exigência legal, sempre com aviso prévio
          quando o aviso for possível.
        </p>
        <p>
          Após o encerramento, você tem <strong>30 dias</strong> para exportar seus dados. Passado
          esse prazo, eles são excluídos conforme a seção 9 da Política de Privacidade.
        </p>
      </Secao>

      <Secao id="mudancas" titulo="13. Mudanças nestes termos">
        <p>
          Podemos atualizar estes termos. A data no topo da página indica a versão vigente. Mudanças
          relevantes serão comunicadas por e-mail ou dentro do sistema com pelo menos 30 dias de
          antecedência; continuar usando o serviço depois desse prazo significa aceitá-las.
        </p>
      </Secao>

      <Secao id="foro" titulo="14. Lei aplicável e foro">
        <p>
          Estes termos são regidos pela lei brasileira. Antes de qualquer medida judicial, procure-nos
          em{" "}
          <a className="text-primary-600 hover:underline" href={`mailto:${CONTROLADOR.email}`}>
            {CONTROLADOR.email}
          </a>
          : quase tudo se resolve por conversa. Não havendo acordo, fica eleito o foro da comarca do
          domicílio do assinante consumidor; nos demais casos, o da sede de{" "}
          {CONTROLADOR.razaoSocial}.
        </p>
      </Secao>
    </LegalLayout>
  );
}
