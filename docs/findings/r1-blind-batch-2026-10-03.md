# R1: the blind batch, 276 pairs, 2026-10-03

**Status: READ BLIND (Corey's rulings, 2026-10-03, ruling 2).** 251 unanimous, 16 split, 9 not linked.
- All 93 readers passed the check. The batch cost 9,789,893 tokens, and its canary 32,733.
- **Every link from this batch is held until Corey has read his ten** (`r1-corey-ten-2026-10-03.md`).

## How it was read

- **The pairs:** the 276 person-list pairs not yet read blind, the 239 first-load pairs and the 37 earlier candidates. The person list's other 5 were read blind in the control.
- **The runs:** grouped by docket and date into runs of up to 9, as calibrated. That made 31 runs, each staged as one file named by its content hash.
- **The readers:** one per lens per run, 93 in all. Each was launched by the Agent tool from the stored launcher (sha256 `b6f45a4c2975`), in 6 waves. After the pricing wave, the largest files went first.
- **A canary went first and passed** (`docs/reads/2026-10-03-blind-batch-canary.json`).
- **The check now also requires that a reader saw every line of its file, as the file holds it.** One Read returns about 41,000 characters, so a run's file takes several. Every reader did.
- **The check admits one more harness attachment, measured on the first wave:** the Read tool's truncation notice, which names the file and where the next read starts. A notice naming any other file fails its reader.
- **The record is `docs/reads/2026-10-03-blind-batch.json`:** every reader's start hash, checks, verdicts and tokens.

## The price

A reader's tokens are its final context, the measure the blind re-reads used (`r1-blind-reads-2026-10-03.md`).

- **The estimate before the batch went past its first wave: 9,868,392 tokens, under the 10,000,000 ceiling.**
  - The first wave read six runs spanning the file sizes, from the smallest (35,174 characters) to the largest (250,361): 18 readers.
  - Each reader's tokens were fitted against its file's size, and the fit summed over all 93 readers.
- **The batch was re-priced after every wave, on every reader measured so far.** The next wave launched only while the estimate stayed under the ceiling.

| after wave | readers measured | fit, tokens per reader | the batch, estimated | spent so far |
|---|---|---|---|---|
| 1 | 18 | 68,822 + 0.476 x characters | 9,868,392 | 2,109,921 |
| 2 | 36 | 71,198 + 0.448 x characters | 9,881,138 | 4,345,976 |
| 3 | 54 | 71,759 + 0.448 x characters | 9,935,018 | 6,224,382 |
| 4 | 72 | 71,340 + 0.451 x characters | 9,917,540 | 7,973,771 |
| 5 | 90 | 68,189 + 0.473 x characters | 9,787,179 | 9,524,430 |
| 6 | 93 | 68,262 + 0.473 x characters | 9,789,893 | 9,789,893 |

**Each fit, tried on the wave after it:**

- Wave 2's 18 readers used 2,236,055 tokens; wave 1's fit predicted 2,263,447 (-1.2%).
- Wave 3's 18 readers used 1,878,406 tokens; wave 2's fit predicted 1,847,088 (+1.7%).
- Wave 4's 18 readers used 1,749,389 tokens; wave 3's fit predicted 1,760,906 (-0.7%).
- Wave 5's 18 readers used 1,550,659 tokens; wave 4's fit predicted 1,674,293 (-7.4%).
- Wave 6's 3 readers used 265,463 tokens; wave 5's fit predicted 262,703 (+1.1%).

**Actual: 9,789,893 tokens, -0.8% on the first estimate.**

## The outcomes

| | pairs | of the 37 earlier candidates |
|---|---|---|
| unanimous | 251 | 36 |
| split | 16 | 1 |
| not linked | 9 | 0 |

**By the shape of the pair:**

| the pair joins | unanimous | split | not linked |
|---|---|---|---|
| a RECAP document's description and docket text, matched on words (`short_long`) | 234 | 13 | 6 |
| a RECAP document's description and docket text, matched on type alone (`type_only`) | 9 | 0 | 1 |
| two docket texts, equal (`long_twin_eq`) | 8 | 0 | 0 |
| two RECAP document descriptions, one over 60 characters (`short_long`) | 0 | 3 | 2 |

**No pair joining two RECAP document descriptions passed.** The rule reads a description over 60 characters, such as an order's description joined with "AND", as a long form. All five such pairs failed the bar.

### Not linked (9)

Each read gives identity / alternative match / clocks (y yes, u uncertain, n no).

| rows | matched as | runs held them | earlier candidate | reads |
|---|---|---|---|---|
| 279/282 | `short_long` | first-load |  | y (better match 463654829) / u (better match 463654829) / u (better match 463654829) |
| 5308/5476 | `short_long` | first-load |  | n (better match 439194970) / n (better match 439194970) / n (better match 439194970) |
| 7137/7143 | `short_long` | first-load |  | u (better match 468502354) / y / u (better match 468502354) |
| 15567/15575 | `short_long` | first-load |  | y / u (better match 449882851) / u (better match 449882851) |
| 85450/85526 | `short_long` | first-load |  | n (better match 442772628) / n (better match 442772628) / n (better match 442772628) |
| 91472/91753 | `short_long` | first-load |  | n (better match 461627079) / n (better match 461627079) / n (better match 461627079) |
| 91687/91727 | `short_long` | first-load |  | u (better match 476882060) / u (better match 476882060) / u (better match 476882060) |
| 91926/91997 | `short_long` | first-load |  | u (better match 463107114) / u (better match 463107114) / u (better match 463107114) |
| 92455/92574 | `type_only` | first-load |  | n (better match 461851764) / n (better match 461851764) / n (better match 461851764) |

**Six of the nine are the failure mode the bar exists for:** a short form paired on its type with a different minute entry of the same day (5308/5476, 85450/85526, 91472/91753, 91687/91727, 91926/91997, 92455/92574).

**In the other three, the better match is an object the readers took for another view of the same entry**, which CourtListener then holds three times:
- **15567/15575 and 279/282:** the pair's long form is itself a RECAP document's description, over 60 characters. The better match is the order's docket text.
- **7137/7143:** the better match is a second short form, created 78 seconds before the docket text. The pair's short form has no filing time and was created about 36 hours after the docket text.

### Split: to Corey's split list (16)

Each read gives identity / alternative match / clocks (y yes, u uncertain, n no).

| rows | matched as | runs held them | earlier candidate | reads |
|---|---|---|---|---|
| 5392/5456 | `short_long` | first-load |  | y / y / u |
| 5401/5477 | `short_long` | first-load |  | y / y / u |
| 5402/5424 | `short_long` | first-load |  | y / y / u |
| 5420/5470 | `short_long` | first-load |  | y / y / u |
| 6966/6967 | `short_long` | first-load |  | u / u / u |
| 13741/13777 | `short_long` | first-load |  | y / y / u |
| 13752/13787 | `short_long` | first-load |  | y / y / u |
| 13889/13891 | `short_long` | first-load |  | y / y / u |
| 13988/14009 | `short_long` | first-load |  | y / y / u |
| 13990/13992 | `short_long` | first-load |  | y / y / u |
| 17904/17923 | `short_long` | first-load |  | y / y / u |
| 17905/17930 | `short_long` | first-load |  | y / y / u |
| 17906/17931 | `short_long` | first-load |  | y / y / u |
| 17913/17922 | `short_long` | first-load |  | y / y / u |
| 17929/17937 | `short_long` | first-load |  | y / y / u |
| 93146/93298 | `short_long` | cross-run | yes | y / y / u |

**Fifteen of the sixteen turn on a short form with no filing time.** Each was created 1 to 48 days after its entry's date, so the clocks reader found nothing tying it to its entry below the day.
- In fourteen of them, identity and alternative match read yes.
- The sixteenth, 93146/93298, has a timed short form. Its long form has no filing time and was created two days later.

### Unanimous (251): candidates, held

48/50, 52/59, 54/57, 251/314, 253/256, 255/299, 261/276, 265/301, 267/297, 269/313, 270/317, 272/294, 280/288, 289/305, 505/577, 4059/12693, 5391/5434, 5393/5463, 5399/5427, 5400/5461, 5414/5415, 5417/5453, 5429/5466, 5479/5481, 6083/6166, 6122/6168, 6139/6167, 6307/6353, 6308/6359, 6309/6351, 6336/6352, 6761/6845, 6762/6846, 6767/6834, 6777/6835, 6783/6832, 6790/6833, 6809/6842, 6810/6844, 6813/6838, 6821/6840, 6848/6972, 6862/6978, 6869/6955, 6876/6976, 6877/6975, 6879/6974, 6886/6962, 6892/6969, 6894/6977, 6913/6961, 6916/6963, 6918/6964, 6923/6970, 6960/6968, 7085/7145, 7092/7131, 7100/7138, 7105/7129, 7112/7133, 7115/7142, 7127/7144, 7205/7206, 7466/7534, 7475/7543, 7523/7565, 7533/7540, 7548/7550, 7556/7579, 7576/7581, 7591/7724, 7626/7725, 7673/7708, 7714/17501, 7738/7832, 7742/7831, 7744/7837, 7781/7835, 7782/7836, 7785/7838, 7789/7845, 7796/7842, 7797/7834, 7817/7847, 7826/7843, 8794/8795, 8870/8872, 10326/10327, 10328/10344, 10329/10337, 10330/10367, 10331/10366, 10334/10362, 10336/10347, 10338/10356, 10342/10348, 10350/10354, 10355/10364, 10438/10501, 10460/10494, 10465/10480, 10499/10506, 10510/10511, 13576/13580, 13577/13582, 13578/13579, 13581/13583, 13718/13763, 13719/13744, 13720/13762, 13722/13723, 13725/13796, 13727/13746, 13728/13737, 13729/13779, 13730/13760, 13731/13778, 13732/13783, 13734/13755, 13742/13758, 13747/13748, 13756/13766, 13767/13781, 13768/13770, 13784/13789, 13785/13792, 13788/13797, 13798/13801, 13979/14012, 13980/13995, 13981/13993, 13982/14001, 13983/14007, 13984/13999, 13985/14010, 13986/13996, 13987/14004, 13989/14005, 13994/13997, 14002/14011, 14006/14008, 14013/14015, 14014/14016, 15530/15578, 15553/15574, 15563/15564, 17758/17921, 17808/17938, 17865/17952, 17869/17948, 17878/17942, 17879/17944, 17886/17928, 17911/17945, 27277/29042, 27574/37917, 54722/54724, 68098/68128, 81820/82168, 85205/85337, 85211/85329, 85278/85325, 85286/85327, 85292/85333, 85295/85330, 85297/85331, 85394/85396, 85397/85409, 85398/85414, 85400/85405, 85402/85403, 85407/85419, 85410/85421, 85411/85416, 85412/85418, 85413/85415, 85417/85422, 85439/85517, 85446/85523, 85448/85511, 85470/85525, 85475/85515, 85480/85506, 85490/85507, 85497/85536, 85503/85510, 87390/87543, 88676/88680, 89061/89683, 89874/90160, 89883/90093, 90158/90178, 90159/90179, 90205/91351, 91417/91771, 91481/91750, 91501/91747, 91516/91759, 91520/91762, 91546/91757, 91555/91777, 91558/91769, 91564/91734, 91573/91763, 91576/91773, 91587/91746, 91594/91733, 91601/91742, 91607/91731, 91616/91772, 91624/91754, 91630/91744, 91657/91739, 91697/91776, 91714/91770, 91715/91768, 91717/91761, 91718/91764, 91720/91758, 91721/91756, 91723/91736, 91724/91735, 91779/92014, 91808/92003, 91875/92007, 91893/92017, 91909/91995, 91914/91999, 91919/92001, 91921/91996, 91936/92009, 91941/92000, 91949/92008, 91956/91993, 91974/92015, 91982/91992, 92019/92199, 92026/92211, 92067/92210, 92073/92209, 92085/92208, 92089/92201, 92121/92193, 92135/92192, 92156/92195, 92157/92194, 92189/92207, 92190/92206, 92364/92365, 92577/92579, 92655/92657

**Corey's ten are drawn from these with seed 20261003** (`r1-corey-ten-2026-10-03.md`).

## Outside the batch

Ruling 2 reads *"Every tier-2 link comes from this batch."* It is applied to the links still to be made.

- **The 8 links already made stand:** the rule's 7 and pair 23. They were re-read blind on 2026-10-03 under the same launcher, all unanimous (`r1-blind-reads-2026-10-03.md`), and they are not among the 276.
- **The blind control's 5 unrefused pairs are not among the 276 either.** It read n=8 of the 2026-10-01 sample and person pair 4 unanimous, and n=3, pair 5 and pair 15 split (`r1-blind-reads-2026-10-03.md`).
  - n=8 and pair 4 have no link from this batch, so they stay on the person list.
  - **For Corey:** whether they join the batch's unanimous passes.
