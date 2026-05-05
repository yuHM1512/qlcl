Re-organize database structure & UX of QC Input:
- Sá»­ dá»¥ng láº¡i "Chi tiáº¿t" tá»« báº£ng "dm_chi_tiet" Ä‘á»ƒ nháº­p:
Giá» Ä‘Ã¢y khi sáº½ nháº­p lá»—i theo tá»«ng "Bá»™ pháº­n" vÃ  "Chi tiáº¿t", flow gá»“m:
1. Chá»n bá»™ pháº­n - Chá»n chi tiáº¿t (dropdown) (1 bá»™ pháº­n cÃ³ thá»ƒ cÃ³ nhiá»u chi tiáº¿t)
- 1 combo bá»™ pháº­n + chi tiáº¿t nháº­p giá»‘ng nhÆ° cÅ©
Äá»‘i  khá»‘i thÃ nh thÃªm "Bá»™ pháº­n - Chi tiáº¿t má»›i"
Tá»« "Nháº­p theo bá»™ pháº­n" => sang nháº­p theo "Bá»™ pháº­n - Chi tiáº¿t"

Bá»• sung thÃªm thÃ´ng tin má»©c Ä‘á»™, sau khi Ä‘iá»n sá»‘ lÆ°á»£ng cho 1 "MÃ£ lá»—i".
Logic má»©c Ä‘á»™: check trong dm_mo_ta_loi: náº¿u mÃ£ lá»—i Ä‘Ã³ chá»‰ cÃ³ 1 má»©c Ä‘á»™, frontend tá»± láº¥y Ä‘á»ƒ khi lÆ°u ghi vÃ o 1 cá»™t muc_do: migrate add thÃªm cá»™t vÃ o qc_defect (SP), cáº§n 2 cá»™t má»›i:
- chi_tiet
- muc_do
Náº¿u 1 mÃ£ lá»—i cÃ³ 2 má»©c Ä‘á»™  trá»Ÿ lÃªn => hiá»‡n droplist tÆ°Æ¡ng á»©ng Ä‘á»ƒ user chá»n (tá»« json)
