# 国家统计局外部数据说明

本目录是 DS 2043 选题 07 外部数据的补充收集，只保存国家统计局官网的原始文件，不做清洗、不改数、不删行。
不改动 `07_external` 中已收集的 catalogs / impact / context 文件。

## 收集范围

已确认范围：

1. 《中国统计年鉴》中的「地震灾害情况」表（全国时间序列 + 当年分省损失口径，以各年年鉴实际表名为准）。
2. 分省年末常住人口（近年多为「分地区年末人口数」；较早年鉴多为「各地区总人口和出生率、死亡率、自然增长率」等同类表）。
3. 分省地区生产总值（近年多为「地区生产总值（某年）」；较早年鉴多为「各地区国内生产总值」或「各地区生产总值和指数」）。

另外，官网「环境统计资料 / 环境统计数据」中有独立的「地震灾害情况」分省表（以及部分全国序列），作为同一官方口径的补充一并保存。
未收集：地震监测、地质灾害、各类自然灾害合计损失、香港/澳门/台湾本地生产总值、支出法或项目结构表、全国核算总表。

## 来源与入口

- 中国统计年鉴目录：<https://www.stats.gov.cn/sj/ndsj/>
  - 2005–2025 年：`/sj/ndsj/{year}/left.htm`（frameset 目录在 `indexch.htm`）。
  - 2004 年：`/sj/ndsj/yb2004-c/left.htm`
  - 2003 年：官方发布整本 PDF `/sj/ndsj/yearbook2003_c.pdf`，本批未拆表。
  - 2002 年：`/yearbook2001/ml/2002_c.htm`
  - 2001 年：`/sj/ndsj/2001c/mulu.htm` 及各章目录
  - 2000 年：`/sj/ndsj/zgnj/mulu.html` 及各章目录
  - 1999 年：`/yearbook/ml/1999_c.htm`
- 环境统计资料：<https://www.stats.gov.cn/zt_18555/ztsj/hjtjzl/>（入口会转到最近年份 2014；目录中列出 1999、2003–2014 年）。
- 国家数据网站 `https://data.stats.gov.cn/` 本次从收集环境无法作为来源（见探测记录），因此不以该站为准。

## 口径说明

- 「地震灾害次数」只统计造成人员伤亡或直接经济损失的事件，不等于全部 M≥5 地震；有的年份也包括 5.0 级以下成灾地震，以及震中在境外但影响境内的事件（表注中常以 * 标出）。
- 年鉴表的资料来源：较早年份注明中国地震局，近年年鉴「资源和环境」篇简要说明中注明地震灾害等情况由应急管理部提供。
- 环境统计资料中的分省地震灾害表，资料来源同样标注为中国地震局。该系列在官网目前更新到 2014 年。
- 分省人口、地区生产总值为中国部分后续分析的暴露度支撑，不是地震目录本身。
- 近两年年鉴表多为官方 JPG；较早年份常见 HTML，并可能附带 Excel。均保留官网原始格式，不在本步转录为 CSV。

## 抓取信息

- 抓取开始：2026-11-15 16:22:54 UTC+08:00
- 抓取结束：2026-11-15 16:37:07 UTC+08:00
- User-Agent：`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36`
- 目的：BNBU DS 2043 课程项目学术使用。
- 著作权与使用：文件版权归国家统计局及原资料提供单位；本目录仅保存官网公开页面/文件，用于课程学习。具体转载与使用以国家统计局网站声明为准。

## 本次收集结果（原始文件，未清洗）

- 保存文件数：452
- 已分类的年鉴「地震灾害情况」表（按年鉴年份）：[2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
- 已分类的分省人口表（按年鉴年份）：[1999, 2000, 2001, 2002, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
- 已分类的地区生产总值表（按年鉴年份）：[1999, 2000, 2001, 2002, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
- 环境统计资料中的地震灾害表（按资料年份）：[1999, 2003, 2004, 2005, 2006, 2007, 2008, 2010, 2011, 2012, 2013, 2014]

## 备注与缺口

- data.stats.gov.cn probe: HTTP 200, 3198 bytes, final=https://data.stats.gov.cn/dg/website/page.html#/pc/national/home
- Yearbook 1999: no table classified as earthquake_disaster in parsed TOC(s)
- Yearbook 2000: no table classified as earthquake_disaster in parsed TOC(s)
- Yearbook 2001: no table classified as earthquake_disaster in parsed TOC(s)
- Yearbook 2002: no table classified as earthquake_disaster in parsed TOC(s)
- Yearbook 2003: official site publishes a single PDF (yearbook2003_c.pdf), not an HTML table TOC; raw PDF saved, tables not extracted.
- Environment stats 2009: no 地震灾害 table found in paginated index
- Yearbook 2009: no standalone 分地区年末人口数 / 各地区人口数 table; saved 「各地区人口的城乡构成和出生率、死亡率、自然增长率」 as the closest official provincial population table.
- Yearbook 2010: no standalone 分地区年末人口数 / 各地区人口数 table; saved 「各地区人口的城乡构成和出生率、死亡率、自然增长率」 as the closest official provincial population table.

## 分类清单

| 年份 | 来源 | 类别 | 表名 | 相对路径 |
| --- | --- | --- | --- | --- |
| 1999 | yearbook | regional_gdp | c08-各地区国内生产总值和指数 | `yearbook/yearbook/1999/c08c.htm` |
| 1999 | yearbook | regional_gdp | c09-各地区国内生产总值(1998年) | `yearbook/yearbook/1999/c09c.htm` |
| 1999 | yearbook | provincial_population | D03-各地区总人口和出生率、死亡率、自然增长率(1998年) | `yearbook/yearbook/1999/d03c.htm` |
| 2000 | yearbook | regional_gdp | C08各地区国内生产总值和指数 | `yearbook/sj/ndsj/zgnj/2000/C08c.htm` |
| 2000 | yearbook | regional_gdp | C09各地区国内生产总值(1999年) | `yearbook/sj/ndsj/zgnj/2000/C09c.htm` |
| 2000 | yearbook | provincial_population | D03各地区总人口和出生率、死亡率、自然增长率(1999年) | `yearbook/sj/ndsj/zgnj/2000/D03c.htm` |
| 2001 | yearbook | regional_gdp | 3-8各地区国内生产总值和指数 | `yearbook/sj/ndsj/2001c/c0308c.htm` |
| 2001 | yearbook | regional_gdp | 3-9各地区国内生产总值(2000年) | `yearbook/sj/ndsj/2001c/c0309c.htm` |
| 2001 | yearbook | provincial_population | 4-3各地区总人口和性别比 | `yearbook/sj/ndsj/2001c/d0403c.htm` |
| 2002 | yearbook | regional_gdp | 3-8各地区国内生产总值和指数 | `yearbook/yearbook2001/2002/c0308c.htm` |
| 2002 | yearbook | regional_gdp | 3-9各地区国内生产总值(2001年) | `yearbook/yearbook2001/2002/c0309c.htm` |
| 2002 | yearbook | provincial_population | 4-3各地区总人口和出生率、死亡率、自然增长率(2001年) | `yearbook/yearbook2001/2002/d0403c.htm` |
| 2004 | yearbook | regional_gdp | 3-10各地区生产总值和指数 | `yearbook/sj/ndsj/yb2004-c/html/C0310ac.htm` |
| 2004 | yearbook | regional_gdp | 3-11各地区生产总值(2003年) | `yearbook/sj/ndsj/yb2004-c/html/C0311ac.htm` |
| 2004 | yearbook | provincial_population | 4-3各地区总人口和出生率、死亡率、自然增长率(2003年） | `yearbook/sj/ndsj/yb2004-c/html/D0403ac.htm` |
| 2004 | yearbook | earthquake_disaster | 12-26地震灾害情况 | `yearbook/sj/ndsj/yb2004-c/html/L1226ac.htm` |
| 2005 | yearbook | regional_gdp | 3-10地区生产总值和指数 | `yearbook/sj/ndsj/2005/html/C0310C.HTM` |
| 2005 | yearbook | regional_gdp | 3-11地区生产总值(2004年) | `yearbook/sj/ndsj/2005/html/C0311C.HTM` |
| 2005 | yearbook | provincial_population | 4-3各地区总人口和出生率、死亡率、自然增长率(2004年) | `yearbook/sj/ndsj/2005/html/D0403C.HTM` |
| 2005 | yearbook | earthquake_disaster | 12-26地震灾害情况 | `yearbook/sj/ndsj/2005/html/L1226C.HTM` |
| 2007 | yearbook | regional_gdp | 3-12地区生产总值和指数 | `yearbook/sj/ndsj/2007/html/C0312C.HTM` |
| 2007 | yearbook | regional_gdp | 3-13地区生产总值(2006年) | `yearbook/sj/ndsj/2007/html/C0313C.HTM` |
| 2007 | yearbook | regional_gdp | 3-14地区生产总值收入法构成项目(2006年) | `yearbook/sj/ndsj/2007/html/C0314C.HTM` |
| 2007 | yearbook | earthquake_disaster | 12-29地震灾害情况 | `yearbook/sj/ndsj/2007/html/L1229C.HTM` |
| 2008 | yearbook | regional_gdp | 2-14地区生产总值和指数 | `yearbook/sj/ndsj/2008/html/C0214C.HTM` |
| 2008 | yearbook | regional_gdp | 2-15地区生产总值(2007年) | `yearbook/sj/ndsj/2008/html/C0215C.HTM` |
| 2008 | yearbook | regional_gdp | 2-16地区生产总值收入法构成项目(2007年) | `yearbook/sj/ndsj/2008/html/C0216C.HTM` |
| 2008 | yearbook | earthquake_disaster | 11-43地震灾害情况 | `yearbook/sj/ndsj/2008/html/L1143C.HTM` |
| 2009 | yearbook | regional_gdp | 2-14地区生产总值和指数 | `yearbook/sj/ndsj/2009/html/C0214C.HTM` |
| 2009 | yearbook | regional_gdp | 2-15按三次产业分地区生产总值(2008年) | `yearbook/sj/ndsj/2009/html/C0215C.HTM` |
| 2009 | yearbook | regional_gdp | 2-16地区生产总值收入法构成项目(2007年) | `yearbook/sj/ndsj/2009/html/C0216C.HTM` |
| 2009 | yearbook | earthquake_disaster | 11-45地震灾害情况 | `yearbook/sj/ndsj/2009/html/L1145C.HTM` |
| 2010 | yearbook | regional_gdp | 2-14地区生产总值和指数 | `yearbook/sj/ndsj/2010/html/C0214C.HTM` |
| 2010 | yearbook | regional_gdp | 2-15按三次产业分地区生产总值(2009年) | `yearbook/sj/ndsj/2010/html/C0215C.HTM` |
| 2010 | yearbook | regional_gdp | 2-16地区生产总值收入法构成项目(2009年) | `yearbook/sj/ndsj/2010/html/C0216C.HTM` |
| 2010 | yearbook | earthquake_disaster | 12-45地震灾害情况 | `yearbook/sj/ndsj/2010/html/L1245C.HTM` |
| 2011 | yearbook | regional_gdp | 2-14地区生产总值和指数 | `yearbook/sj/ndsj/2011/html/C0214C.HTM` |
| 2011 | yearbook | regional_gdp | 2-15按三次产业分地区生产总值(2010年) | `yearbook/sj/ndsj/2011/html/C0215C.HTM` |
| 2011 | yearbook | regional_gdp | 2-16地区生产总值收入法构成项目(2010年) | `yearbook/sj/ndsj/2011/html/C0216C.HTM` |
| 2011 | yearbook | provincial_population | 3-4各地区总人口和出生率、死亡率、自然增长率(2010年) | `yearbook/sj/ndsj/2011/html/D0304C.HTM` |
| 2011 | yearbook | provincial_population | 3-7各地区总人口和性别比 | `yearbook/sj/ndsj/2011/html/D0307C.HTM` |
| 2011 | yearbook | provincial_population | 3-13各地区年末人口数 | `yearbook/sj/ndsj/2011/html/D0313C.HTM` |
| 2011 | yearbook | earthquake_disaster | 12-47地震灾害情况 | `yearbook/sj/ndsj/2011/html/L1247C.HTM` |
| 2012 | yearbook | regional_gdp | 2-14地区生产总值和指数 | `yearbook/sj/ndsj/2012/html/C0214C.HTM` |
| 2012 | yearbook | regional_gdp | 2-15按三次产业分地区生产总值(2011年) | `yearbook/sj/ndsj/2012/html/C0215C.HTM` |
| 2012 | yearbook | regional_gdp | 2-16地区生产总值收入法构成项目(2011年) | `yearbook/sj/ndsj/2012/html/C0216C.HTM` |
| 2012 | yearbook | provincial_population | 3-4各地区年末人口数 | `yearbook/sj/ndsj/2012/html/D0304C.HTM` |
| 2012 | yearbook | earthquake_disaster | 12-36地震灾害情况 | `yearbook/sj/ndsj/2012/html/L1236C.HTM` |
| 2013 | yearbook | regional_gdp | 2-14地区生产总值和指数 | `yearbook/sj/ndsj/2013/html/Z0214C.htm` |
| 2013 | yearbook | regional_gdp | 2-15人均地区生产总值和指数 | `yearbook/sj/ndsj/2013/html/Z0215C.htm` |
| 2013 | yearbook | regional_gdp | 2-16按三次产业分地区生产总值(2012年) | `yearbook/sj/ndsj/2013/html/Z0216C.htm` |
| 2013 | yearbook | regional_gdp | 2-17地区生产总值收入法构成项目(2012年) | `yearbook/sj/ndsj/2013/html/Z0217C.htm` |
| 2013 | yearbook | provincial_population | 3-5分地区年末人口数 | `yearbook/sj/ndsj/2013/html/Z0305C.htm` |
| 2013 | yearbook | earthquake_disaster | 7-34地震灾害情况 | `yearbook/sj/ndsj/2013/html/Z0734C.htm` |
| 2014 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2014/zk/html/Z0205C.HTM` |
| 2014 | yearbook | regional_gdp | 3-14地区生产总值和指数 | `yearbook/sj/ndsj/2014/zk/html/Z0314C.HTM` |
| 2014 | yearbook | regional_gdp | 3-15人均地区生产总值和指数 | `yearbook/sj/ndsj/2014/zk/html/Z0315C.HTM` |
| 2014 | yearbook | regional_gdp | 3-16按三次产业分地区生产总值(2013年) | `yearbook/sj/ndsj/2014/zk/html/Z0316C.HTM` |
| 2014 | yearbook | regional_gdp | 3-17地区生产总值收入法构成项目(2012年) | `yearbook/sj/ndsj/2014/zk/html/Z0317C.HTM` |
| 2014 | yearbook | earthquake_disaster | 8-34地震灾害情况 | `yearbook/sj/ndsj/2014/zk/html/Z0834C.HTM` |
| 2015 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2015/html/CH0205.jpg` |
| 2015 | yearbook | regional_gdp | 3-9地区生产总值和指数 | `yearbook/sj/ndsj/2015/html/CH0309.jpg` |
| 2015 | yearbook | regional_gdp | 3-10人均地区生产总值和指数 | `yearbook/sj/ndsj/2015/html/CH0310.jpg` |
| 2015 | yearbook | regional_gdp | 3-11按三次产业分地区生产总值(2014年) | `yearbook/sj/ndsj/2015/html/CH0311.jpg` |
| 2015 | yearbook | regional_gdp | 3-12地区生产总值收入法构成项目(2014年) | `yearbook/sj/ndsj/2015/html/CH0312.jpg` |
| 2015 | yearbook | earthquake_disaster | 8-35地震灾害情况 | `yearbook/sj/ndsj/2015/html/CH0835.jpg` |
| 2016 | yearbook | provincial_population | 2-6分地区年末人口数 | `yearbook/sj/ndsj/2016/html/0206CH.jpg` |
| 2016 | yearbook | regional_gdp | 3-9地区生产总值和指数 | `yearbook/sj/ndsj/2016/html/0309CH.jpg` |
| 2016 | yearbook | regional_gdp | 3-10人均地区生产总值和指数 | `yearbook/sj/ndsj/2016/html/0310CH.jpg` |
| 2016 | yearbook | regional_gdp | 3-11按三次产业分地区生产总值(2015年) | `yearbook/sj/ndsj/2016/html/0311CH.jpg` |
| 2016 | yearbook | regional_gdp | 3-12地区生产总值收入法构成项目(2015年) | `yearbook/sj/ndsj/2016/html/0312CH.jpg` |
| 2016 | yearbook | earthquake_disaster | 8-35地震灾害情况 | `yearbook/sj/ndsj/2016/html/0835CH.jpg` |
| 2017 | yearbook | provincial_population | 2-6分地区年末人口数 | `yearbook/sj/ndsj/2017/html/CH0206.jpg` |
| 2017 | yearbook | regional_gdp | 3-9地区生产总值(2016年) | `yearbook/sj/ndsj/2017/html/CH0309.jpg` |
| 2017 | yearbook | regional_gdp | 3-10地区生产总值收入法构成项目(2016年) | `yearbook/sj/ndsj/2017/html/CH0310.jpg` |
| 2017 | yearbook | earthquake_disaster | 8-35地震灾害情况 | `yearbook/sj/ndsj/2017/html/CH0835.jpg` |
| 2018 | yearbook | provincial_population | 2-6分地区年末人口数 | `yearbook/sj/ndsj/2018/html/CH0206.jpg` |
| 2018 | yearbook | regional_gdp | 3-9地区生产总值(2017年) | `yearbook/sj/ndsj/2018/html/CH0309.jpg` |
| 2018 | yearbook | regional_gdp | 3-10地区生产总值收入法构成项目(2017年) | `yearbook/sj/ndsj/2018/html/CH0310.jpg` |
| 2018 | yearbook | earthquake_disaster | 8-32地震灾害情况 | `yearbook/sj/ndsj/2018/html/CH0835.jpg` |
| 2019 | yearbook | provincial_population | 2-6分地区年末人口数 | `yearbook/sj/ndsj/2019/html/C0206.jpg` |
| 2019 | yearbook | regional_gdp | 3-9地区生产总值(2018年) | `yearbook/sj/ndsj/2019/html/C0309.jpg` |
| 2019 | yearbook | earthquake_disaster | 8-33地震灾害情况 | `yearbook/sj/ndsj/2019/html/C0833.jpg` |
| 2020 | yearbook | provincial_population | 2-6分地区年末人口数 | `yearbook/sj/ndsj/2020/html/C0206.jpg` |
| 2020 | yearbook | regional_gdp | 3-9地区生产总值(2019年) | `yearbook/sj/ndsj/2020/html/C0309.jpg` |
| 2020 | yearbook | earthquake_disaster | 8-32地震灾害情况 | `yearbook/sj/ndsj/2020/html/C0833.jpg` |
| 2021 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2021/html/C02-05.jpg` |
| 2021 | yearbook | provincial_population | 2-5分地区年末人口数 [companion] | `yearbook/sj/ndsj/2021/html/C02-05.xls` |
| 2021 | yearbook | regional_gdp | 3-9地区生产总值(2020年) | `yearbook/sj/ndsj/2021/html/C03-09.jpg` |
| 2021 | yearbook | regional_gdp | 3-9地区生产总值(2020年) [companion] | `yearbook/sj/ndsj/2021/html/C03-09.xls` |
| 2021 | yearbook | earthquake_disaster | 8-31地震灾害情况 | `yearbook/sj/ndsj/2021/html/C08-32.jpg` |
| 2021 | yearbook | earthquake_disaster | 8-31地震灾害情况 [companion] | `yearbook/sj/ndsj/2021/html/C08-32.xls` |
| 2022 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2022/html/C02-05.jpg` |
| 2022 | yearbook | regional_gdp | 3-9地区生产总值(2021年) | `yearbook/sj/ndsj/2022/html/C03-09.jpg` |
| 2022 | yearbook | earthquake_disaster | 8-31地震灾害情况 | `yearbook/sj/ndsj/2022/html/C08-31.jpg` |
| 2023 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2023/html/C02-05.jpg` |
| 2023 | yearbook | regional_gdp | 3-9地区生产总值(2022年) | `yearbook/sj/ndsj/2023/html/C03-09.jpg` |
| 2023 | yearbook | earthquake_disaster | 8-31地震灾害情况 | `yearbook/sj/ndsj/2023/html/C08-31.jpg` |
| 2024 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2024/html/C02-05.jpg` |
| 2024 | yearbook | regional_gdp | 3-9地区生产总值(2023年) | `yearbook/sj/ndsj/2024/html/C03-09.jpg` |
| 2024 | yearbook | earthquake_disaster | 8-31地震灾害情况 | `yearbook/sj/ndsj/2024/html/C08-31.jpg` |
| 2025 | yearbook | provincial_population | 2-5分地区年末人口数 | `yearbook/sj/ndsj/2025/html/C02-05.jpg` |
| 2025 | yearbook | regional_gdp | 3-9地区生产总值(2024年) | `yearbook/sj/ndsj/2025/html/C03-09.jpg` |
| 2025 | yearbook | earthquake_disaster | 8-30地震灾害情况 | `yearbook/sj/ndsj/2025/html/C08-30.jpg` |
| 1999 | environment_stats | earthquake_disaster | 全国五级以上地震灾害情况（1999年） | `environment_stats/zt_18555/ztsj/hjtjzl/1999/202303/t20230302_1923199.html` |
| 2003 | environment_stats | earthquake_disaster | 地震灾害情况(2003年) | `environment_stats/zt_18555/ztsj/hjtjzl/2003/202303/t20230302_1923029.html` |
| 2004 | environment_stats | earthquake_disaster | 地震灾害情况（2004年） | `environment_stats/zt_18555/ztsj/hjtjzl/2004/202303/t20230302_1922923.html` |
| 2005 | environment_stats | earthquake_disaster | 地震灾害情况（2005年） | `environment_stats/zt_18555/ztsj/hjtjzl/2005/202303/t20230302_1922809.html` |
| 2006 | environment_stats | earthquake_disaster | 地震灾害情况(2006年) | `environment_stats/zt_18555/ztsj/hjtjzl/2006/202303/t20230302_1922631.html` |
| 2007 | environment_stats | earthquake_disaster | 地震灾害情况(2007年) | `environment_stats/zt_18555/ztsj/hjtjzl/2007/202303/t20230302_1922437.html` |
| 2008 | environment_stats | earthquake_disaster | 地震灾害情况(2008年) | `environment_stats/zt_18555/ztsj/hjtjzl/2008/202303/t20230302_1922218.html` |
| 2010 | environment_stats | earthquake_disaster | 地震灾害情况(2010年) | `environment_stats/zt_18555/ztsj/hjtjzl/2010/202303/t20230302_1921736.html` |
| 2011 | environment_stats | earthquake_disaster | 9-4地震灾害情况(2011年) | `environment_stats/zt_18555/ztsj/hjtjzl/2011/202303/t20230302_1921503.html` |
| 2012 | environment_stats | earthquake_disaster | 9-4地震灾害情况(2012年) | `environment_stats/zt_18555/ztsj/hjtjzl/2012/202303/t20230302_1921266.html` |
| 2013 | environment_stats | earthquake_disaster | 9-4地震灾害情况(2013年) | `environment_stats/zt_18555/ztsj/hjtjzl/2013/202303/t20230302_1921032.html` |
| 2014 | environment_stats | earthquake_disaster | 9-4地震灾害情况(2014年) | `environment_stats/zt_18555/ztsj/hjtjzl/2014/202303/t20230303_1924049.html` |
| 2006 | yearbook | regional_gdp | 3-8地区生产总值和指数 | `yearbook/sj/ndsj/2006/html/C0308C.HTM` |
| 2006 | yearbook | regional_gdp | 3-9地区生产总值(2005年) | `yearbook/sj/ndsj/2006/html/C0309C.HTM` |
| 2006 | yearbook | provincial_population | 4-3各地区人口数和出生率、死亡率、自然增长率(2005年) | `yearbook/sj/ndsj/2006/html/D0403C.HTM` |
| 2006 | yearbook | earthquake_disaster | 12-29地震灾害情况 | `yearbook/sj/ndsj/2006/html/L1229C.HTM` |
| 2007 | yearbook | provincial_population | 4-3各地区人口数和出生率、死亡率、自然增长率(2006年) | `yearbook/sj/ndsj/2007/html/D0403C.HTM` |
| 2008 | yearbook | provincial_population | 3-3各地区人口数和出生率、死亡率、自然增长率(2007年) | `yearbook/sj/ndsj/2008/html/D0303C.HTM` |
| 2009 | yearbook | provincial_population | 3-4各地区人口的城乡构成和出生率、死亡率、自然增长率(2008年) | `yearbook/sj/ndsj/2009/html/D0304C.HTM` |
| 2010 | yearbook | provincial_population | 3-4各地区人口的城乡构成和出生率、死亡率、自然增长率(2009年) | `yearbook/sj/ndsj/2010/html/D0304C.HTM` |
| 1999 | environment_stats | earthquake_disaster | 全国五级以上地震发生次数(1999年） | `environment_stats/zt_18555/ztsj/hjtjzl/1999/202303/t20230302_1923200.html` |

