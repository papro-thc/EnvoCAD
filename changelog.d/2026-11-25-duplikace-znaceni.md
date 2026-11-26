- **Duplikovat list rozvaděče: značení podle schématu generátoru** – kopie listu rozvaděče dostane předponu podle druhu
  rozvaděče (RDC, RFVE.DC, RFVE.AC, HR, RVN, RE; `generator.spec.board_kind_of_ref` / `next_board_ref`) a první volné číslo
  v projektu (RDC2, RFVE.DC1…); značení se propíše do bloku, názvu listu, `loc` a registru „+“. Rozvaděč, jehož druh se
  z označení nepozná, se duplikuje jako dřív. Test `test_duplicate_sheet_marking.py`.
