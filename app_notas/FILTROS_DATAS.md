# Data de referência das consultas e relatórios

Histórico e BI/relatórios, no navegador e no desktop, permitem escolher **Data de colheita** ou **Data de plantio**. O padrão continua sendo colheita. A API aceita `date_reference=data_colheita` (padrão) ou `date_reference=data_plantio`; outros valores são rejeitados antes da composição do SQL.

O período inclusivo seleciona notas pela coluna escolhida, sem modificar datas ou registros. Contagens, dias ativos, rankings, pendências, Excel bruto/fluxo e os seis PDFs usam a mesma referência de seleção. O diário agrupa pela data escolhida; a coluna Data do Excel de fluxo também corresponde a ela. PDFs informam a referência em todas as páginas; planilhas acrescentam a coluna Data de referencia. As duas datas reais continuam disponíveis no relatório detalhado, no histórico e nos dados brutos.

O fechamento de safra continua anual (ano da data final), conforme o comportamento anterior, usando a referência escolhida para selecionar as notas daquele ano. As datas de início/fim dos rankings de origem e destino nesse relatório continuam descrevendo os respectivos eventos de colheita/plantio; não são alteradas ou deduzidas. O histórico de fazendas de muda preserva a consulta das primeiras/últimas datas de todo o histórico das fazendas presentes no período, agora segundo a referência escolhida.

Notas sem data de plantio não entram em períodos por plantio e não recebem preenchimento automático. A seleção não muda a semântica de `talhao`: ele continua sendo exclusivamente o talhão de origem. O talhão de destino não foi criado.

Não há migração nem alteração do esquema. A instalação operacional não participa desta implementação ou de seus testes.
