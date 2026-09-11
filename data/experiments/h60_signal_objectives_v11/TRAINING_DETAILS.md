# v11实际训练明细

所有数据来自原本地快照；30次新拟合、10份原模型复用。没有下载行情，也没有2026样本。

模型统一StandardScaler + Ridge(alpha=100, solver=svd)，81列固定顺序。每个Y年度模型仅训练截至Y-2且标签已成熟的样本；Y-1用于诊断，不参与调参或重新拟合。模型文件不是当前部署模型。

| 模型 | 年度 | 训练行 | 验证行 | 评分行 | 拟合秒 | 训练标签最晚结束 | 模型SHA256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain_magnitude | 2016 | 10380 | 5730 | 7560 | 0.266 | 2014-12-31 | 7ce75a0122654fcd336ea37a1fcad54dd2b87a59ae876bf9affb30c2bffd7519 |
| stopped_magnitude | 2016 | 10380 | 5730 | 7560 | 0.211 | 2014-12-31 | 0a0dbd960d69b4619cad7d1e4ba7cd2ee7d8fa9de04fe3ae3c53c376be617147 |
| stopped_rank | 2016 | 10380 | 5730 | 7560 | 0.260 | 2014-12-31 | 117a45be4d9c2e0c4b06b3f6632b1ae57219915c889bdef7fa4fd2ea08fa168f |
| plain_magnitude | 2017 | 17940 | 5730 | 7530 | 0.325 | 2015-12-31 | a1bcd8f784bdff1a2f9de93fb68ca982dd350f52122fcc5ec92e30393c41a1dc |
| stopped_magnitude | 2017 | 17940 | 5730 | 7530 | 0.345 | 2015-12-31 | 04f22261d45ec5876be1561466dde22c6a4ccadb7df59756acc40fe2f0d5e26d |
| stopped_rank | 2017 | 17940 | 5730 | 7530 | 0.390 | 2015-12-31 | dd88a00b988ae8248b1841ba9fb898313b3c635b91649ea581008f6005a129b8 |
| plain_magnitude | 2018 | 25500 | 5700 | 7530 | 0.478 | 2016-12-30 | ae011d5fde3f1ffd6deb43c7849602ee9973c92a112137249e946db313acf3ce |
| stopped_magnitude | 2018 | 25500 | 5700 | 7530 | 0.426 | 2016-12-30 | c896053b456aabc57e446a2fa6cf74099cd5d888707495a445f964b58ee0fe46 |
| stopped_rank | 2018 | 25500 | 5700 | 7530 | 0.432 | 2016-12-30 | e9ddecb3e31c4f17eeeca5ee2363491252589666954791525c034d2391a62856 |
| plain_magnitude | 2019 | 33030 | 5700 | 7560 | 0.580 | 2017-12-29 | 85a3ceda2657c88e2c1ba56a34622903031a1b4eac3f9dc2158bb390dbbf01df |
| stopped_magnitude | 2019 | 33030 | 5700 | 7560 | 0.564 | 2017-12-29 | 559f744ec548ee522d231a2a960b57bf718532b9b41c48368155236eafc1ddbd |
| stopped_rank | 2019 | 33030 | 5700 | 7560 | 0.573 | 2017-12-29 | 49704a3e24916e8bb4ba6dfa480fcc18c602ba4277922bc93cfa5743bb3260cf |
| plain_magnitude | 2020 | 40560 | 5730 | 7590 | 0.722 | 2018-12-31 | f9eba4a428576b1d2566a89a472a44f7894497431b1800a1bef2f1b0732b1c4a |
| stopped_magnitude | 2020 | 40560 | 5730 | 7590 | 0.683 | 2018-12-31 | a208cf504e77b51185aed04d9f63732d9a655b158feb2b5920b4d2addb9b645b |
| stopped_rank | 2020 | 40560 | 5730 | 7590 | 0.790 | 2018-12-31 | a54b23743cee95606dfa0dd8a83e0ad4bf6c8cec574f8944506e13e433e6490a |
| plain_magnitude | 2021 | 48120 | 5760 | 7560 | 0.947 | 2019-12-31 | 1468eb96ee92d765d662c0eb00a0bcbf2e15ec9a1a3cb05136082fde66a66f48 |
| stopped_magnitude | 2021 | 48120 | 5760 | 7560 | 0.853 | 2019-12-31 | dd479309c187c7cb8ad3593100aefe032bd0d201fb23348c75c939f35ac91461 |
| stopped_rank | 2021 | 48120 | 5760 | 7560 | 1.228 | 2019-12-31 | 465ced069600f25a267d940c62e42a1b83c0d5d49b9dc74565a6af3fcca2173f |
| plain_magnitude | 2022 | 55710 | 5730 | 7530 | 1.205 | 2020-12-31 | 3ec06b613ce86cb56598db5469366e15fce168aa74f112ce7cb9ae1c5f6b4045 |
| stopped_magnitude | 2022 | 55710 | 5730 | 7530 | 1.144 | 2020-12-31 | f2b4a373e55346a2a2fe3eb9201fb73ee86bdc90cea9f88c44d857596169b5a2 |
| stopped_rank | 2022 | 55710 | 5730 | 7530 | 1.185 | 2020-12-31 | 3ff84c4579e2ab1102ebe65567f94128d75af1b52df45fdcbd97432bc51eaecd |
| plain_magnitude | 2023 | 63270 | 5700 | 7500 | 1.250 | 2021-12-31 | bb9fd129dc5ca055aba7ef9dc28dc84976eee804a1523279f366440f60162ec3 |
| stopped_magnitude | 2023 | 63270 | 5700 | 7500 | 1.215 | 2021-12-31 | 9a41dd80361d3d9564a9fc234800e485de63037fab2e01c2db20b5dc01eea5d3 |
| stopped_rank | 2023 | 63270 | 5700 | 7500 | 1.214 | 2021-12-31 | fc2bb1732580f71501881229ddd86edff9f644cb7923bb1929798c14783653ad |
| plain_magnitude | 2024 | 70800 | 5670 | 7560 | 1.368 | 2022-12-30 | 791d6ecafe14d6020379b810989084785bb38d273fadbc0d83ab6c8d9b6f937f |
| stopped_magnitude | 2024 | 70800 | 5670 | 7560 | 1.504 | 2022-12-30 | 27bf1246a7efd9bacb367b1dc935d23987566be7e58898b1cde55ba80ba4082d |
| stopped_rank | 2024 | 70800 | 5670 | 7560 | 1.611 | 2022-12-30 | c4285ac2ca86a91a9d4f6cd5bcebb3235ac51bf7d5933146c7f73774a02972de |
| plain_magnitude | 2025 | 78300 | 5730 | 7320 | 1.473 | 2023-12-29 | b3c15102e95863686295e04e56c0b838593b555def37eadb0e39eb62b898e7b8 |
| stopped_magnitude | 2025 | 78300 | 5730 | 7320 | 1.433 | 2023-12-29 | d6ebbb25c1134d8c31a8f0e61ef2088775d2f68213f9375ac0e660fcb2f255cf |
| stopped_rank | 2025 | 78300 | 5730 | 7320 | 1.603 | 2023-12-29 | 7bc8da62c23acd34748c4152347c78a1b0de70e4433713a67360e711d7a0ee23 |

训练和验证MSE保存在training_summary.csv；收益数值与排名的单位不同，不能直接比较MSE宣布模型变强。60日标签重叠、同日股票相关，因此训练行数不等于独立观测数。

逐份模型与合同在models/；baseline原模型SHA和逐年预测重算误差在BASELINE_REUSE_CHECK.json，冻结原输入在INPUT_IDENTITY.json。labels.csv保留每笔路径，scores.csv保存全部75,240行开发评分。
