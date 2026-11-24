- **CI: delší limit testů** – job Testy má `timeout-minutes` 60 místo 45; Windows s Pythonem 3.14 se do 45 min
  těsně nevešel a běhy se rušily bez chyby. Soubor `.github/workflows/ci.yml`.
