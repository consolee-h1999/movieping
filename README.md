# Movieping

Match your public Letterboxd **watchlist** or **list** against screenings at DC-area venues, then post results to Discord.

## Local setup

```bash
python3 -m venv projects
source projects/bin/activate
pip install -r requirements.txt
cp users.example.json users.json   # if needed
# Edit users.json with your Letterboxd username
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python main.py
```

## GitHub setup

1. Push this repo to GitHub.
2. **Settings → Secrets → Actions** — add:
   - `DISCORD_WEBHOOK_URL` — your Discord channel webhook URL.
   - `USERS_JSON` (optional) — full contents of `users.json` if you don’t want to commit it.
3. **Settings → Pages** — Source: branch `main`, folder `/docs`.
4. Site: `https://<your-user>.github.io/movieping/`

The signup page generates a JSON entry to paste into `users.json`. v1 does not auto-save signups from the web form.

## Users config

`users.json`:

```json
{
  "users": [
    {
      "name": "Coco",
      "email": "you@example.com",
      "letterboxd_username": "cocoxx",
      "letterboxd_list": null,
      "enabled": true
    }
  ]
}
```

- `letterboxd_list`: list slug from the URL `letterboxd.com/<user>/list/<slug>/`, or `null` for watchlist.
- `letterboxd_username` / list must be **public** on Letterboxd.

## Automation

`.github/workflows/movieping.yml` runs daily (and on manual dispatch). It scrapes venues once, then checks each enabled user.

**Cinemas that work today:** Miracle Theatre, Library of Congress, Sunset Cinema.

**Possible V2 improvements:** Alamo Drafthouse, Kennedy Center.

## Discord webhook (added note)
I currently have MoviePing send alerts to my Discord channel for this, but soon (by V2), I may have it invite all users into that channel (and maybe even group them by city) so they can also receive automated notifications if they don't wish to receive them via email. 


