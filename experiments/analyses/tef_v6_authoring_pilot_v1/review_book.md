# TEF-RAG v6 Authoring Pilot v1 Review Book

Status: `AUTHORING_PILOT_UNREVIEWED`

Review: `PENDING_USER_AND_CHATGPT_REVIEW`

## PILOT-C01 — MULTI_EPISODE_DISAMBIGUATION

- Asset: 1号电池簇（280Ah-class LFP）
- Summary: 区分上周单探头漂移与本周多点持续升温/风机退化。

Timeline:

- 2026-09-08T14:03:00+08:00 · BMS · 上周14:03，1号电池簇7号温度探头由32.1°C瞬时跳至50.8°C，一分钟后回到33.0°C；相邻三个探头没有同步变化。
- 2026-09-08T14:12:00+08:00 · inspection · 上周现场红外复核显示7号电芯对应区域32.6°C，未见局部热点。
- 2026-09-08T14:25:00+08:00 · maintenance_log · 上周事件结论为7号温度探头漂移，工单要求校准探头。
- 2026-09-15T10:20:00+08:00 · BMS · 今天10:20至10:45，1号电池簇相邻四个测点由32°C持续升至43°C，趋势同步且未自行回落。
- 2026-09-15T10:31:00+08:00 · SCADA · 今天10:31，风道压差由常态42 Pa升至78 Pa，同时散热风机转速从额定值的92%降至61%。
- 2026-09-15T10:49:00+08:00 · inspection · 现场检查确认散热风机叶轮转动不稳，进风口无大面积遮挡。
- 2026-09-15T10:56:00+08:00 · maintenance_log · 本次多点持续温升结合压差与转速变化，判断为散热风机退化，不沿用上周探头漂移结论。
- 2026-09-15T11:02:00+08:00 · work_order · 工单要求降低该簇充电负荷并检修散热风机；探头校准不作为本次主处置。

Queries:

- 2026-09-15T11:05:00+08:00 · 当前这次持续温升能否沿用上周的探头漂移结论，处置应依据哪些记录？
- 2026-09-15T11:05:00+08:00 · 上周与今天的温升记录分别指向什么原因，今天的工单应处理哪个部件？

Required groups / canonical flow (current_cause):

- Groups: obs=[PILOT-C01-E04, PILOT-C01-E05]; dx=[PILOT-C01-E07]; act=[PILOT-C01-E08]
- Flow: PILOT-C01-Q01-G01-obs → PILOT-C01-Q01-G02-dx ; PILOT-C01-Q01-G02-dx → PILOT-C01-Q01-G03-act

Required groups / canonical flow (episode_compare):

- Groups: history=[PILOT-C01-E01, PILOT-C01-E02]; current=[PILOT-C01-E04, PILOT-C01-E06]; decision=[PILOT-C01-E07, PILOT-C01-E08]
- Flow: PILOT-C01-Q02-G01-history → PILOT-C01-Q02-G03-decision ; PILOT-C01-Q02-G02-current → PILOT-C01-Q02-G03-decision

## PILOT-C02 — MULTI_EPISODE_DISAMBIGUATION

- Asset: 2号电池簇（280Ah-class LFP）
- Summary: 区分六月连接点局部热点与九月冷却通道阻塞造成的整排升温。

Timeline:

- 2026-06-18T16:10:00+08:00 · BMS · 六月事件中2号簇仅12号电芯温度比相邻点高9°C，其他测点稳定。
- 2026-06-18T16:24:00+08:00 · inspection · 红外检查在12号电芯连接排发现集中热点，紧固标记有位移。
- 2026-06-18T17:05:00+08:00 · work_order · 六月工单重新紧固连接排并复测，热点消失。
- 2026-09-15T08:40:00+08:00 · BMS · 今天2号簇靠近出风侧的一整排测点在25分钟内由31°C升至40°C，没有单一连接点突升。
- 2026-09-15T08:46:00+08:00 · SCADA · 出风侧风量比同柜另一通道低38%，风机转速指令与反馈一致。
- 2026-09-15T09:02:00+08:00 · inspection · 检查发现出风格栅被脱落的过滤棉局部堵塞，连接排无变色、无松动。
- 2026-09-15T09:12:00+08:00 · maintenance_log · 本次整排升温归因于冷却通道阻塞，排除沿用六月连接点接触异常。
- 2026-09-15T09:18:00+08:00 · work_order · 工单要求停用该通道、清除脱落滤棉并复测风量；不安排连接排拆检。

Queries:

- 2026-09-15T09:20:00+08:00 · 今天的升温是否是六月连接点故障复发，当前应执行哪项处置？
- 2026-09-15T09:20:00+08:00 · 为区分两次升温，应调取哪些历史与本次检查记录？

Required groups / canonical flow (today):

- Groups: pattern=[PILOT-C02-E04, PILOT-C02-E05]; cause=[PILOT-C02-E07]; action=[PILOT-C02-E08]
- Flow: PILOT-C02-Q01-G01-pattern → PILOT-C02-Q01-G02-cause ; PILOT-C02-Q01-G02-cause → PILOT-C02-Q01-G03-action

Required groups / canonical flow (records):

- Groups: old=[PILOT-C02-E02, PILOT-C02-E03]; new=[PILOT-C02-E04, PILOT-C02-E06]; decision=[PILOT-C02-E07]
- Flow: PILOT-C02-Q02-G01-old → PILOT-C02-Q02-G03-decision ; PILOT-C02-Q02-G02-new → PILOT-C02-Q02-G03-decision

## PILOT-C03 — CUTOFF_SENSITIVE

- Asset: 3号电池簇（280Ah-class LFP）
- Summary: 同一温升任务在红外离线上传前后改变合法诊断与工单。

Timeline:

- 2026-09-15T09:10:00+08:00 · BMS · 3号簇7号探头连续6分钟为47.8°C，相邻点保持31至33°C。
- 2026-09-15T09:18:00+08:00 · maintenance_log · 初步判断为局部电芯异常升温，建议限功率并等待现场复核。
- 2026-09-15T09:24:00+08:00 · work_order · 临时工单要求检查7号电芯连接部位和散热风道，暂不恢复高倍率充电。
- 2026-09-15T09:31:00+08:00 · inspection · 09:31已完成红外检查：对应表面32.4°C，邻区31.8至32.7°C，未见局部热点；移动终端离线，记录10:06才上传。
- 2026-09-15T09:43:00+08:00 · BMS · 一致性检查显示7号探头长期偏离附近三个探头，其他探头没有同步升温。
- 2026-09-15T10:08:00+08:00 · maintenance_log · 复核诊断撤销09:18局部电芯热异常，当前更符合温度传感器漂移。
- 2026-09-15T10:15:00+08:00 · work_order · 更新工单取消电芯拆检，改为温度探头校验；校验前保持倍率限制。
- 2026-09-15T10:18:00+08:00 · operator_log · 值班员确认新工单已替代09:24临时工单。

Queries:

- 2026-09-15T09:50:00+08:00 · 截至当前，本次单点温升应以哪版诊断处置，现场还需完成什么复核？
- 2026-09-15T10:20:00+08:00 · 截至当前，本次单点温升应以哪版诊断处置，现场还需完成什么复核？

Required groups / canonical flow (same_task_before):

- Groups: obs=[PILOT-C03-E01, PILOT-C03-E05]; dx=[PILOT-C03-E02]; act=[PILOT-C03-E03]
- Flow: PILOT-C03-Q01-G01-obs → PILOT-C03-Q01-G02-dx ; PILOT-C03-Q01-G02-dx → PILOT-C03-Q01-G03-act

Required groups / canonical flow (same_task_after):

- Groups: obs=[PILOT-C03-E04, PILOT-C03-E05]; dx=[PILOT-C03-E06]; act=[PILOT-C03-E07, PILOT-C03-E08]
- Flow: PILOT-C03-Q02-G01-obs → PILOT-C03-Q02-G02-dx ; PILOT-C03-Q02-G02-dx → PILOT-C03-Q02-G03-act

## PILOT-C04 — CUTOFF_SENSITIVE

- Asset: PCS-04直流侧通信单元
- Summary: 同一失联任务在网关缓存补传和告警更正前后改变支持证据。

Timeline:

- 2026-09-15T13:02:00+08:00 · SCADA · SCADA连续报PCS-04下属两簇通信中断，最后实时帧停在13:01。
- 2026-09-15T13:05:00+08:00 · PCS · PCS本机面板显示功率控制与直流电压稳定，未触发停机保护。
- 2026-09-15T13:09:00+08:00 · network_log · 站控网对边缘网关的心跳丢失，但PCS本机端口仍有链路灯。
- 2026-09-15T13:14:00+08:00 · maintenance_log · 初步按设备通信中断处理，要求检查PCS至交换机链路。
- 2026-09-15T13:18:00+08:00 · work_order · 临时工单安排切换备用网口并保留PCS运行。
- 2026-09-15T13:21:00+08:00 · gateway_log · 边缘网关恢复后补传13:02至13:19缓存，显示PCS数据连续采集，缺口位于网关上行。
- 2026-09-15T13:45:00+08:00 · maintenance_log · 告警更正为边缘网关上行延迟，不再认定PCS本体通信中断。
- 2026-09-15T13:49:00+08:00 · work_order · 工单撤回PCS备用网口切换，改查网关上行交换端口与缓存队列。

Queries:

- 2026-09-15T13:30:00+08:00 · 截至当前，这次数据中断应定位在哪一段链路，现有工单是否应继续？
- 2026-09-15T13:55:00+08:00 · 截至当前，这次数据中断应定位在哪一段链路，现有工单是否应继续？

Required groups / canonical flow (same_task_before):

- Groups: alarm=[PILOT-C04-E01, PILOT-C04-E03]; dx=[PILOT-C04-E04]; act=[PILOT-C04-E05]
- Flow: PILOT-C04-Q01-G01-alarm → PILOT-C04-Q01-G02-dx ; PILOT-C04-Q01-G02-dx → PILOT-C04-Q01-G03-act

Required groups / canonical flow (same_task_after):

- Groups: alarm=[PILOT-C04-E06, PILOT-C04-E02]; dx=[PILOT-C04-E07]; act=[PILOT-C04-E08]
- Flow: PILOT-C04-Q02-G01-alarm → PILOT-C04-Q02-G02-dx ; PILOT-C04-Q02-G02-dx → PILOT-C04-Q02-G03-act

## PILOT-C05 — LATE_ARRIVING_EVIDENCE

- Asset: 液冷机组LCU-05
- Summary: 离线巡检照片晚到后把低液位判断从蒸发损耗改为接头渗漏。

Timeline:

- 2026-09-15T07:50:00+08:00 · SCADA · LCU-05储液罐液位一周内由68%缓慢降至55%，供回液温差未突变。
- 2026-09-15T08:02:00+08:00 · SCADA · 液位下降速率超过班组观察阈值，系统提示检查补液需求。
- 2026-09-15T08:15:00+08:00 · maintenance_log · 在未见泄漏证据时，初步记录为长期运行后的自然损耗，计划少量补液。
- 2026-09-15T08:22:00+08:00 · work_order · 工单安排确认液体型号后补液，并观察24小时液位。
- 2026-09-15T08:34:00+08:00 · inspection · 08:34巡检照片清楚显示回液接头下方有新鲜油状湿痕，接头周围积尘形成冲刷线；地下室无网络，09:28上传。
- 2026-09-15T08:48:00+08:00 · SCADA · 停泵保压后回液支路压力继续缓慢下降，其他支路稳定。
- 2026-09-15T09:32:00+08:00 · maintenance_log · 诊断更正为回液接头渗漏，自然损耗不再作为当前解释。
- 2026-09-15T09:38:00+08:00 · work_order · 撤回直接补液工单，先隔离支路、处理接头并通过保压试验后再补液。

Queries:

- 2026-09-15T09:10:00+08:00 · 截至09:10，液位下降最合理的暂定解释是什么，补液前还缺哪项现场证据？
- 2026-09-15T09:45:00+08:00 · 截至09:45，液位下降应按什么原因处理，原补液工单是否仍适用？

Required groups / canonical flow (before):

- Groups: obs=[PILOT-C05-E01, PILOT-C05-E06]; dx=[PILOT-C05-E03]; act=[PILOT-C05-E04]
- Flow: PILOT-C05-Q01-G01-obs → PILOT-C05-Q01-G02-dx ; PILOT-C05-Q01-G02-dx → PILOT-C05-Q01-G03-act

Required groups / canonical flow (after):

- Groups: obs=[PILOT-C05-E05, PILOT-C05-E06]; dx=[PILOT-C05-E07]; act=[PILOT-C05-E08]
- Flow: PILOT-C05-Q02-G01-obs → PILOT-C05-Q02-G02-dx ; PILOT-C05-Q02-G02-dx → PILOT-C05-Q02-G03-act

## PILOT-C06 — LATE_ARRIVING_EVIDENCE

- Asset: 汇流柜BCP-06
- Summary: 晚到的离线扭矩复核表改变母排温升的原因与返工范围。

Timeline:

- 2026-09-15T15:02:00+08:00 · thermal_monitor · BCP-06 B相母排接点在相同负荷下比A、C相高11°C，温差连续三次巡检扩大。
- 2026-09-15T15:08:00+08:00 · SCADA · 三相电流平衡，B相没有额外负载，柜内风机反馈正常。
- 2026-09-15T15:16:00+08:00 · maintenance_log · 初步怀疑接点表面氧化，建议停电后清洁接触面。
- 2026-09-15T15:20:00+08:00 · work_order · 工单安排次日停电清洁B相接触面并复测。
- 2026-09-15T15:34:00+08:00 · inspection · 15:34离线扭矩复核发现B相两颗紧固件低于本次作业卡设定值，复核表因平板未同步于16:12上传。
- 2026-09-15T15:38:00+08:00 · inspection · 紧固件防松标记偏移，接触面未见明显氧化痕迹。
- 2026-09-15T16:18:00+08:00 · maintenance_log · 诊断改为紧固不足导致接触电阻升高，原表面氧化判断撤销。
- 2026-09-15T16:24:00+08:00 · work_order · 更新工单要求按批准作业卡复紧两颗紧固件、重做防松标记并红外复测。

Queries:

- 2026-09-15T15:55:00+08:00 · 截至15:55，B相接点温升应按什么暂定原因安排停电作业？
- 2026-09-15T16:30:00+08:00 · 截至16:30，新增复核记录支持什么原因，停电作业范围应如何调整？

Required groups / canonical flow (before):

- Groups: obs=[PILOT-C06-E01, PILOT-C06-E02]; dx=[PILOT-C06-E03]; act=[PILOT-C06-E04]
- Flow: PILOT-C06-Q01-G01-obs → PILOT-C06-Q01-G02-dx ; PILOT-C06-Q01-G02-dx → PILOT-C06-Q01-G03-act

Required groups / canonical flow (after):

- Groups: obs=[PILOT-C06-E05, PILOT-C06-E06]; dx=[PILOT-C06-E07]; act=[PILOT-C06-E08]
- Flow: PILOT-C06-Q02-G01-obs → PILOT-C06-Q02-G02-dx ; PILOT-C06-Q02-G02-dx → PILOT-C06-Q02-G03-act

## PILOT-C07 — SUPERSEDED_DIAGNOSIS

- Asset: 7号电池簇（280Ah-class LFP）
- Summary: 红外与探头一致性复核撤销局部电芯过热诊断并改派校验工单。

Timeline:

- 2026-09-15T09:10:00+08:00 · BMS · 7号簇19号温度通道报48.2°C，相邻通道保持32°C左右。
- 2026-09-15T09:17:00+08:00 · maintenance_log · 初诊为19号电芯局部过热，要求限制充电。
- 2026-09-15T09:23:00+08:00 · work_order · 临时工单安排拆检19号电芯连接部位。
- 2026-09-15T09:36:00+08:00 · inspection · 红外测得对应区域32.7°C，无局部热点。
- 2026-09-15T09:44:00+08:00 · BMS · 通道对调测试后高读数随采集通道移动，未随电芯位置移动。
- 2026-09-15T09:52:00+08:00 · maintenance_log · 09:17局部过热诊断被撤销，改判为采集通道偏移。
- 2026-09-15T09:58:00+08:00 · work_order · 新工单取消电芯拆检，改为校验采集模块并继续限功率。
- 2026-09-15T10:18:00+08:00 · maintenance_log · 校验后该通道与相邻通道温差回到0.8°C，限功率待班长解除。

Queries:

- 2026-09-15T10:05:00+08:00 · 本次高温告警当前应以哪版诊断为准，原拆检工单还有效吗？
- 2026-09-15T10:20:00+08:00 · 哪些记录证明高读数来自采集通道而非电芯本体，处置是否已验证？

Required groups / canonical flow (valid_dx):

- Groups: check=[PILOT-C07-E04, PILOT-C07-E05]; dx=[PILOT-C07-E06]; act=[PILOT-C07-E07]
- Flow: PILOT-C07-Q01-G01-check → PILOT-C07-Q01-G02-dx ; PILOT-C07-Q01-G02-dx → PILOT-C07-Q01-G03-act

Required groups / canonical flow (basis):

- Groups: obs=[PILOT-C07-E01, PILOT-C07-E05]; dx=[PILOT-C07-E06]; result=[PILOT-C07-E08]
- Flow: PILOT-C07-Q02-G01-obs → PILOT-C07-Q02-G02-dx ; PILOT-C07-Q02-G02-dx → PILOT-C07-Q02-G03-result

## PILOT-C08 — SUPERSEDED_DIAGNOSIS

- Asset: 8号电池舱排风单元
- Summary: 清网后温差仍扩大，旧堵塞诊断被风机轴承退化诊断覆盖并重开工单。

Timeline:

- 2026-09-15T11:00:00+08:00 · SCADA · 8号舱排风量下降且舱内温差由3°C扩大到7°C。
- 2026-09-15T11:08:00+08:00 · maintenance_log · 初诊为进风滤网堵塞。
- 2026-09-15T11:20:00+08:00 · work_order · 工单完成滤网清洁并关闭。
- 2026-09-15T11:35:00+08:00 · SCADA · 清网后风量仅恢复4%，舱内温差继续扩大。
- 2026-09-15T11:43:00+08:00 · inspection · 风机驱动端振动和异响明显，叶轮无堵塞。
- 2026-09-15T11:50:00+08:00 · maintenance_log · 滤网堵塞诊断被轴承退化诊断覆盖。
- 2026-09-15T11:56:00+08:00 · work_order · 原工单重开，新增更换风机轴承组件和复测风量。
- 2026-09-15T12:01:00+08:00 · operator_log · 维修前将舱内相关簇限制至低负荷运行。

Queries:

- 2026-09-15T12:05:00+08:00 · 滤网清洁后问题为何仍未解决，当前工单应执行什么？
- 2026-09-15T12:05:00+08:00 · 现在哪条诊断覆盖了原堵塞判断，依据是什么？

Required groups / canonical flow (current):

- Groups: result=[PILOT-C08-E04, PILOT-C08-E05]; dx=[PILOT-C08-E06]; act=[PILOT-C08-E07, PILOT-C08-E08]
- Flow: PILOT-C08-Q01-G01-result → PILOT-C08-Q01-G02-dx ; PILOT-C08-Q01-G02-dx → PILOT-C08-Q01-G03-act

Required groups / canonical flow (supersede):

- Groups: old=[PILOT-C08-E02, PILOT-C08-E03]; new_evidence=[PILOT-C08-E04, PILOT-C08-E05]; new_dx=[PILOT-C08-E06]
- Flow: PILOT-C08-Q02-G01-old → PILOT-C08-Q02-G03-new_dx ; PILOT-C08-Q02-G02-new_evidence → PILOT-C08-Q02-G03-new_dx

## PILOT-C09 — PROCEDURE_VERSIONING

- Asset: 9号电池簇（型号M280-A）
- Summary: 同一单探头高温观测在V1/V2/V3规程下分别触发拆检、红外复核、传感器校验。

Timeline:

- 2026-01-01T00:00:00+08:00 · procedure · M280-A温升处置V1：单探头持续高温先限功率并人工测温，读数仍高则安排电芯检查；有效至4月30日。
- 2026-05-01T00:00:00+08:00 · procedure · M280-A温升处置V2取代V1：增加红外与风道复核；BMS高温但红外无热点时不得直接拆检电芯；有效至8月31日。
- 2026-09-01T00:00:00+08:00 · procedure · M280-A温升处置V3取代V2：在红外正常时增加相邻探头一致性检查；单通道持续偏差优先进入传感器校验。
- 2026-03-10T10:00:00+08:00 · BMS · 3月10日9号簇5号探头持续46°C，相邻点32°C。
- 2026-03-10T10:20:00+08:00 · work_order · 依V1限功率、人工测温后安排电芯连接部位检查。
- 2026-06-10T10:00:00+08:00 · BMS · 6月10日同型设备单探头持续46°C，红外对应区域32.5°C且风道正常。
- 2026-06-10T10:25:00+08:00 · work_order · 依V2保持限功率并停止直接拆检，继续核对测温链路。
- 2026-09-15T10:00:00+08:00 · BMS · 9月15日单通道高读数、红外正常且一致性检查显示偏差随通道移动。
- 2026-09-15T10:30:00+08:00 · work_order · 依V3进入传感器校验流程，不拆检电芯。

Queries:

- 2026-03-10T10:30:00+08:00 · 按当时有效文件，3月这次单探头高温应完成哪些检查？
- 2026-09-15T10:35:00+08:00 · 按当前有效文件，红外正常且偏差随通道移动时应进入哪项处置？

Required groups / canonical flow (v1_task):

- Groups: obs=[PILOT-C09-E04]; proc=[PILOT-C09-E01]; act=[PILOT-C09-E05]
- Flow: PILOT-C09-Q01-G01-obs → PILOT-C09-Q01-G02-proc ; PILOT-C09-Q01-G02-proc → PILOT-C09-Q01-G03-act

Required groups / canonical flow (v3_task):

- Groups: obs=[PILOT-C09-E08]; proc=[PILOT-C09-E03]; act=[PILOT-C09-E09]
- Flow: PILOT-C09-Q02-G01-obs → PILOT-C09-Q02-G02-proc ; PILOT-C09-Q02-G02-proc → PILOT-C09-Q02-G03-act

## PILOT-C10 — PROCEDURE_VERSIONING

- Asset: 液冷机组LCU-10（型号C2）
- Summary: V1/V2/V3逐步加入型号范围、保压前置与泄漏后禁止直接补液。

Timeline:

- 2026-01-01T00:00:00+08:00 · procedure · 液冷补液V1适用于C1/C2：低液位报警后可核对液体型号并补液；有效至3月31日。
- 2026-04-01T00:00:00+08:00 · procedure · 液冷补液V2取代V1：C2机组补液前须停泵保压并检查可见接头；有效至7月31日。
- 2026-08-01T00:00:00+08:00 · procedure · 液冷补液V3取代V2：发现湿痕或保压下降时禁止直接补液，须隔离泄漏支路、修复并通过保压后补液。
- 2026-02-15T08:00:00+08:00 · SCADA · 2月C2机组液位低于班组观察线，无湿痕记录。
- 2026-02-15T08:20:00+08:00 · work_order · 按V1核对介质后补液并恢复。
- 2026-09-15T08:00:00+08:00 · SCADA · 9月LCU-10液位下降且回液支路停泵保压失败。
- 2026-09-15T08:14:00+08:00 · inspection · 回液接头下方发现新鲜湿痕。
- 2026-09-15T08:30:00+08:00 · work_order · 按V3隔离支路并修复接头，保压通过前禁止补液。

Queries:

- 2026-02-15T08:25:00+08:00 · 2月当时有效的文件允许怎样处理低液位？
- 2026-09-15T08:35:00+08:00 · 当前发现湿痕并保压失败后，能否直接补液，必须先做什么？

Required groups / canonical flow (old):

- Groups: obs=[PILOT-C10-E04]; proc=[PILOT-C10-E01]; act=[PILOT-C10-E05]
- Flow: PILOT-C10-Q01-G01-obs → PILOT-C10-Q01-G02-proc ; PILOT-C10-Q01-G02-proc → PILOT-C10-Q01-G03-act

Required groups / canonical flow (current):

- Groups: obs=[PILOT-C10-E06, PILOT-C10-E07]; proc=[PILOT-C10-E03]; act=[PILOT-C10-E08]
- Flow: PILOT-C10-Q02-G01-obs → PILOT-C10-Q02-G02-proc ; PILOT-C10-Q02-G02-proc → PILOT-C10-Q02-G03-act

## PILOT-C11 — CROSS_SOURCE_REQUIRED

- Asset: 11号电池舱
- Summary: BMS温升、SCADA转速、现场异物与型号规程共同决定先清风道后评估风机。

Timeline:

- 2026-09-15T10:00:00+08:00 · BMS · 11号舱靠近出风侧的六个测点在20分钟内由31°C升至39°C。
- 2026-09-15T10:05:00+08:00 · SCADA · 排风机反馈转速为指令的88%，风道压差比邻舱高44%。
- 2026-09-15T10:08:00+08:00 · SCADA · 舱级温差告警触发，但风机未报电机故障。
- 2026-09-15T10:18:00+08:00 · inspection · 现场发现包装薄膜吸附在回风格栅，叶轮无异响。
- 2026-07-22T14:00:00+08:00 · work_order · 同型号舱历史工单记录：清除格栅异物后压差与温差恢复，未更换风机。
- 2026-09-01T00:00:00+08:00 · procedure · 当前型号处置卡要求：压差高且发现风道异物时先停机清障并复测；清障后转速仍低才更换风机。
- 2026-09-15T10:25:00+08:00 · maintenance_log · 综合多源记录，当前优先判断为回风格栅阻塞，暂不足以认定风机损坏。
- 2026-09-15T10:30:00+08:00 · work_order · 工单先隔离风机、清除薄膜并复测压差和温差，复测失败才转风机检修。

Queries:

- 2026-09-15T10:35:00+08:00 · 这次舱内温差扩大应先清理风道还是直接换风机，依据分别来自哪些记录？
- 2026-09-15T10:35:00+08:00 · 哪些跨系统证据共同支持格栅阻塞判断？

Required groups / canonical flow (action):

- Groups: telemetry=[PILOT-C11-E01, PILOT-C11-E02]; field=[PILOT-C11-E04, PILOT-C11-E05]; rule_action=[PILOT-C11-E06, PILOT-C11-E08]
- Flow: PILOT-C11-Q01-G01-telemetry → PILOT-C11-Q01-G02-field ; PILOT-C11-Q01-G02-field → PILOT-C11-Q01-G03-rule_action

Required groups / canonical flow (cause):

- Groups: bms=[PILOT-C11-E01]; scada=[PILOT-C11-E02, PILOT-C11-E03]; inspection_dx=[PILOT-C11-E04, PILOT-C11-E07]
- Flow: PILOT-C11-Q02-G01-bms → PILOT-C11-Q02-G03-inspection_dx ; PILOT-C11-Q02-G02-scada → PILOT-C11-Q02-G03-inspection_dx

## PILOT-C12 — CROSS_SOURCE_REQUIRED

- Asset: 12号电池簇直流回路
- Summary: 绝缘监测、雨后巡检、历史工单和隔离规程共同支持先隔离接线盒而非拆簇。

Timeline:

- 2026-09-15T06:30:00+08:00 · insulation_monitor · 12号簇直流正极对地绝缘值间歇下降，干燥时段曾自行恢复。
- 2026-09-15T06:35:00+08:00 · environment_monitor · 夜间降雨后舱外湿度升高，舱内温湿度正常。
- 2026-09-15T06:40:00+08:00 · BMS · 各电芯电压与温度无同步异常，簇内未报采样故障。
- 2026-09-15T06:52:00+08:00 · inspection · 室外直流接线盒电缆格兰头周围有水迹，箱内下沿潮湿。
- 2026-05-04T09:00:00+08:00 · work_order · 五月同回路雨后绝缘下降曾通过更换接线盒密封圈解决。
- 2026-08-01T00:00:00+08:00 · procedure · 当前绝缘排查卡要求先分段隔离室外接线盒，确认外部回路后方可拆检电池簇。
- 2026-09-15T07:02:00+08:00 · maintenance_log · 现有证据优先指向室外接线盒受潮，不支持直接拆检簇内电芯。
- 2026-09-15T07:08:00+08:00 · work_order · 工单隔离接线盒、干燥并检查格兰头密封，复测绝缘后再决定是否扩大范围。

Queries:

- 2026-09-15T07:15:00+08:00 · 绝缘告警应先检查室外接线盒还是拆检电池簇，完整依据是什么？
- 2026-09-15T07:15:00+08:00 · 哪些不同来源的记录支持受潮判断并限定排查顺序？

Required groups / canonical flow (scope):

- Groups: monitor=[PILOT-C12-E01, PILOT-C12-E03]; field_history=[PILOT-C12-E04, PILOT-C12-E05]; proc_action=[PILOT-C12-E06, PILOT-C12-E08]
- Flow: PILOT-C12-Q01-G01-monitor → PILOT-C12-Q01-G02-field_history ; PILOT-C12-Q01-G02-field_history → PILOT-C12-Q01-G03-proc_action

Required groups / canonical flow (cause):

- Groups: context=[PILOT-C12-E02, PILOT-C12-E01]; inspection=[PILOT-C12-E04]; decision=[PILOT-C12-E07, PILOT-C12-E06]
- Flow: PILOT-C12-Q02-G01-context → PILOT-C12-Q02-G02-inspection ; PILOT-C12-Q02-G02-inspection → PILOT-C12-Q02-G03-decision

## PILOT-C13 — SIMILAR_SYMPTOM_DIFFERENT_CAUSE

- Asset: 13号电池簇（280Ah-class LFP）
- Summary: 两次都叫温升，但早次为传感器漂移，本次为连接点接触异常。

Timeline:

- 2026-08-01T09:00:00+08:00 · BMS · 8月事件中单个温度通道瞬时跳高15°C，邻点不变。
- 2026-08-01T09:12:00+08:00 · inspection · 8月红外未见热点，高读数随通道对调移动。
- 2026-08-01T09:25:00+08:00 · maintenance_log · 8月结论为温度采集通道漂移并完成校验。
- 2026-09-15T14:00:00+08:00 · BMS · 本次17号电芯及相邻连接排温度缓慢升高，负荷下降后仍保持8°C温差。
- 2026-09-15T14:12:00+08:00 · inspection · 红外在17号连接点发现集中热点，探头读数与红外趋势一致。
- 2026-09-15T14:20:00+08:00 · inspection · 停电检查发现连接紧固标记偏移，其他连接点正常。
- 2026-09-15T14:28:00+08:00 · maintenance_log · 本次判断为连接点接触异常，不沿用8月传感器漂移结论。
- 2026-09-15T14:34:00+08:00 · work_order · 工单要求按批准作业卡复紧连接点并红外复测。

Queries:

- 2026-09-15T14:40:00+08:00 · 本次温升与8月记录症状相似，为什么不能沿用传感器漂移结论？
- 2026-09-15T14:40:00+08:00 · 当前应校验探头还是处理连接点，依据和工单是什么？

Required groups / canonical flow (differentiate):

- Groups: old=[PILOT-C13-E01, PILOT-C13-E02]; new=[PILOT-C13-E04, PILOT-C13-E05]; decision=[PILOT-C13-E07]
- Flow: PILOT-C13-Q01-G01-old → PILOT-C13-Q01-G03-decision ; PILOT-C13-Q01-G02-new → PILOT-C13-Q01-G03-decision

Required groups / canonical flow (action):

- Groups: obs=[PILOT-C13-E05, PILOT-C13-E06]; dx=[PILOT-C13-E07]; act=[PILOT-C13-E08]
- Flow: PILOT-C13-Q02-G01-obs → PILOT-C13-Q02-G02-dx ; PILOT-C13-Q02-G02-dx → PILOT-C13-Q02-G03-act

## PILOT-C14 — SIMILAR_SYMPTOM_DIFFERENT_CAUSE

- Asset: 14号电池簇通信链路
- Summary: 两次数据冻结外观相同，历史为采集模块死机，本次为站控上行拥塞。

Timeline:

- 2026-07-03T18:00:00+08:00 · SCADA · 7月14号簇全部采样值同时冻结，采集模块本地也停止刷新。
- 2026-07-03T18:20:00+08:00 · work_order · 7月重启采集模块后本地与站控数据同步恢复。
- 2026-07-03T18:30:00+08:00 · maintenance_log · 7月结论为采集模块死机。
- 2026-09-15T16:00:00+08:00 · SCADA · 本次站控画面冻结，但14号簇采集模块本地时间戳持续更新。
- 2026-09-15T16:06:00+08:00 · gateway_log · 网关队列持续堆积，其他两个簇也出现相同时段上送延迟。
- 2026-09-15T16:12:00+08:00 · network_log · 链路抓包显示上行重传集中，簇内总线报文连续。
- 2026-09-15T16:20:00+08:00 · maintenance_log · 本次定位为站控上行拥塞，不是采集模块死机复发。
- 2026-09-15T16:25:00+08:00 · work_order · 工单清理网关队列并检查上行交换端口，不重启簇内采集模块。

Queries:

- 2026-09-15T16:30:00+08:00 · 本次画面冻结能否按7月故障重启采集模块，为什么？
- 2026-09-15T16:30:00+08:00 · 区分簇内采集故障与上行拥塞需要哪些记录？

Required groups / canonical flow (cause):

- Groups: history=[PILOT-C14-E01, PILOT-C14-E03]; current=[PILOT-C14-E04, PILOT-C14-E05]; decision=[PILOT-C14-E07, PILOT-C14-E08]
- Flow: PILOT-C14-Q01-G01-history → PILOT-C14-Q01-G03-decision ; PILOT-C14-Q01-G02-current → PILOT-C14-Q01-G03-decision

Required groups / canonical flow (records):

- Groups: local=[PILOT-C14-E04]; network=[PILOT-C14-E05, PILOT-C14-E06]; dx=[PILOT-C14-E07]
- Flow: PILOT-C14-Q02-G01-local → PILOT-C14-Q02-G03-dx ; PILOT-C14-Q02-G02-network → PILOT-C14-Q02-G03-dx

## PILOT-C15 — PERSISTENT_UNCERTAINTY

- Asset: 15号电池簇（280Ah-class LFP）
- Summary: 轻微单点温升的红外与一致性检查均不足以区分早期热异常和探头偏差。

Timeline:

- 2026-09-15T09:00:00+08:00 · BMS · 15号簇23号探头从31.8°C缓慢升至36.2°C，相邻点为32.5至33.1°C。
- 2026-09-15T09:12:00+08:00 · BMS · 降负荷后23号读数回落0.6°C但仍高于邻点，趋势不够稳定。
- 2026-09-15T09:20:00+08:00 · inspection · 红外对应区域比邻区高1.2°C，差异接近现场测量重复性范围，未见明确热点。
- 2026-09-15T09:26:00+08:00 · SCADA · 舱内风机转速、风道压差均与邻舱相近。
- 2026-09-15T09:34:00+08:00 · BMS · 探头一致性检查发现轻微固定偏差，但对调测试结果不稳定，不能确认漂移。
- 2026-06-12T10:00:00+08:00 · maintenance_log · 该位置无既往过热维修记录，探头也未做过更换。
- 2026-09-15T09:42:00+08:00 · maintenance_log · 现有证据不足以区分早期局部热异常与温度探头偏差，暂不作唯一诊断。
- 2026-09-15T09:48:00+08:00 · work_order · 保持低负荷监测两小时，使用独立测温复测；温差扩大或出现明确热点时升级隔离。

Queries:

- 2026-09-15T09:55:00+08:00 · 目前能否确定23号位置温升的唯一原因，应如何处置？
- 2026-09-15T09:55:00+08:00 · 哪些现有记录支持保留不确定性，还需要什么复测？

Required groups / canonical flow (status):

- Groups: signals=[PILOT-C15-E01, PILOT-C15-E03]; assessment=[PILOT-C15-E05, PILOT-C15-E07]; plan=[PILOT-C15-E08]
- Flow: PILOT-C15-Q01-G01-signals → PILOT-C15-Q01-G02-assessment ; PILOT-C15-Q01-G02-assessment → PILOT-C15-Q01-G03-plan

Required groups / canonical flow (missing):

- Groups: mixed=[PILOT-C15-E02, PILOT-C15-E03]; uncertainty=[PILOT-C15-E05, PILOT-C15-E07]; next=[PILOT-C15-E08]
- Flow: PILOT-C15-Q02-G01-mixed → PILOT-C15-Q02-G02-uncertainty ; PILOT-C15-Q02-G02-uncertainty → PILOT-C15-Q02-G03-next

## PILOT-C16 — PERSISTENT_UNCERTAINTY

- Asset: 16号电池簇直流回路
- Summary: 间歇绝缘下降既可能来自潮气也可能来自测量链路，检查后仍保留双分支。

Timeline:

- 2026-09-15T05:50:00+08:00 · insulation_monitor · 16号簇对地绝缘值三次短暂下降，均在两分钟内恢复。
- 2026-09-15T05:55:00+08:00 · environment_monitor · 夜间舱外湿度高，但舱内除湿机运行正常。
- 2026-09-15T06:00:00+08:00 · BMS · 电芯电压、温度和簇电流未在绝缘下降时同步变化。
- 2026-09-15T06:12:00+08:00 · inspection · 可见接线盒和电缆入口无水迹，绝缘表面清洁。
- 2026-09-15T06:20:00+08:00 · inspection · 便携表复测期间数值正常，但采集器自检偶发一次参考通道波动。
- 2026-09-15T06:32:00+08:00 · maintenance_log · 短时加强除湿后未再报警，但观察时间不足以证明潮气是原因。
- 2026-09-15T06:40:00+08:00 · maintenance_log · 当前不能区分隐蔽受潮与绝缘监测参考通道偶发偏差，不批准扩大拆检。
- 2026-09-15T06:46:00+08:00 · work_order · 维持监测，安排绝缘监测器比对校验，并在下一次降雨后复查接线盒。

Queries:

- 2026-09-15T06:50:00+08:00 · 这次间歇绝缘下降是否已有明确故障点，当前工单应做什么？
- 2026-09-15T06:50:00+08:00 · 现有证据保留了哪两种可能，下一步如何区分？

Required groups / canonical flow (decision):

- Groups: alarm=[PILOT-C16-E01, PILOT-C16-E03]; limits=[PILOT-C16-E04, PILOT-C16-E05, PILOT-C16-E07]; plan=[PILOT-C16-E08]
- Flow: PILOT-C16-Q01-G01-alarm → PILOT-C16-Q01-G02-limits ; PILOT-C16-Q01-G02-limits → PILOT-C16-Q01-G03-plan

Required groups / canonical flow (branches):

- Groups: moisture=[PILOT-C16-E02, PILOT-C16-E06]; meter_branch=[PILOT-C16-E05]; conclusion=[PILOT-C16-E07, PILOT-C16-E08]
- Flow: PILOT-C16-Q02-G01-moisture → PILOT-C16-Q02-G03-conclusion ; PILOT-C16-Q02-G02-meter_branch → PILOT-C16-Q02-G03-conclusion
