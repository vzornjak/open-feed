# open-feed

Neslužbeni osobni RSS generator za tri emisije. Repozitorij sadrži izvor generatora, konfiguraciju emisija, metapodatke i generirane XML feedove.

| Emisija | RSS za pretplatu |
|---|---|
| KRIK – Krimi petak na Prvom | [krik.xml](https://raw.githubusercontent.com/vzornjak/open-feed/main/krik.xml) |
| Dokumentarna radio drama | [dokumentarna-radio-drama.xml](https://raw.githubusercontent.com/vzornjak/open-feed/main/dokumentarna-radio-drama.xml) |
| Baltazar | [baltazar.xml](https://raw.githubusercontent.com/vzornjak/open-feed/main/baltazar.xml) |

Za pretplatu kopiraj adresu odgovarajućeg RSS-a u podcast aplikaciju. Javni feedovi dostupni su bez privatne kućne mreže.

[feeds.json](feeds.json) definira emisije i izlazne datoteke. [generate_feed.py](generate_feed.py) izrađuje feedove; automatski generirane XML datoteke održava isti postupak.

[Workflow Osvježi open-feed](.github/workflows/update-feed.yml) zakazan je svakih šest sati, u 17. minuti prema UTC-u. Pokreće se i nakon promjene generatora, konfiguracije, testova ili samog workflowa. Ručno osvježavanje dostupno je kroz GitHub Actions → Osvježi open-feed → Run workflow. Svako izvođenje prvo pokreće testove, a zatim sprema promjene feedova i metapodataka kada ih ima. Raspored je planirano vrijeme, ne jamstvo točnog trenutka izvođenja.

Razvojna grana je `main`. Lokalni postupak, usklađen s Python 3.12 okruženjem workflowa:

```sh
python -m unittest -v
python generate_feed.py
```

Generator dohvaća izvore preko mreže i zapisuje izlazne XML datoteke te pripadajuće metapodatke. Prije commita pregledaj nastale razlike.

Izvorni kod dostupan je pod [MIT licencom](LICENSE). Audiozapisi nisu dio repozitorija niti su obuhvaćeni tom licencom.
