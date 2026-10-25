# 7/24 çalıştırma (PC kapalıyken)

Yerel PC kapanınca süreç **durur**. Botun 7/24 devam etmesi için **VPS / cloud** gerekir.

## Hızlı yol: Docker Compose

```bash
cp .env.example .env
# .env içine anahtarlar, TARGET_PRICE, risk limitleri
docker compose up -d --build
```

Dashboard: `http://SUNUCU_IP:8000`  
Uzak erişim için `.env` içinde `NEXORA_API_TOKEN=güçlü-token` ayarla; isteklerde `Authorization: Bearer ...` kullan.

Kalıcı veri: `nexora-data` volume (`paper.sqlite3`, history).

## Railway / Fly.io / herhangi VPS

1. Repo deploy et (Dockerfile hazır).
2. Env vars olarak `.env` içeriğini ekle.
3. Port `8000` (veya platformun `PORT` değeri).
4. Restart policy: always / unless-stopped.

## Güvenlik

- Mainnet için `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY` ve `BINANCE_TESTNET=false`.
- API key'lerde withdraw kapalı olsun.
- Dashboard'u internete açmadan önce token kullan.
