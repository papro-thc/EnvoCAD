- **Testy: charakterizace výkazů** – nové testy zachycují současný výstup výkazů `export/reports.py` (výkaz materiálu,
  kabely, svorky, štítky, kabelový plán, seznam zapojení, výrobní seznam zapojení) na malých projektech z generátoru;
  pokrytí modulu 99 %. Aplikační kód beze změny, dvě podezřelá chování ručních svorek jsou označená `xfail`.
  Test `test_reports_characterization.py`.
