# Sarkari Naukri Live — auto-updating govt job website

Sarkari-style job portal: **Latest Jobs, Admit Card, Result, Answer Key, Syllabus, Important Notice** — official websites se **har 3 ghante me apne-aap** update hota hai, aur Vercel par free host hota hai.

## Ye kaam kaise karta hai

```
GitHub Actions (har 3 ghante)
   │
   ├─ 1. scraper/update.py  → sources.yaml ki official sites kholta hai (UPSC, SSC, IBPS, RRB, MPESB, MPPSC, DSSSB ...)
   │                          naye links dhoondhta hai, category tay karta hai, data/notices.json me jodta hai
   ├─ 2. builder/build.py   → poori website bana deta hai (home boxes, category pages, har notice ka page, sitemap)
   └─ 3. data commit        → Vercel apne-aap site rebuild karke live karta hai
```

- Har notice ka apna page banta hai: title, organisation, date, **official PDF/page ka link**.
- Aapke likhe **Full Detail posts** (fees, age, dates, vacancy table) bhi isi site par aate hain — `content/posts/` me.
- Kaunsi official site kaam kar rahi hai / fail ho rahi hai: **`/status/`** page par dikhta hai.

---

## 1. Hosting (Vercel, free)

1. vercel.com → **Add New → Project** → is GitHub repo ko **Import** karo → **Deploy**. Settings `vercel.json` me pehle se hain, kuch badalna nahi.
2. Site `https://<project>.vercel.app` par live ho jayegi.
3. GitHub Actions har 3 ghante naye notices `data/` me commit karta hai, aur har commit par Vercel khud site dobara deploy kar deta hai.
4. Apna domain lene par: Vercel → Project → **Settings → Domains** me add karo. Sitemap aur canonical links apne-aap naye domain par aa jayenge.

Robot turant chalana ho to: GitHub → **Actions → Auto update site → Run workflow**.

## 2. Naam / settings badalna

Sab kuch **`config.yaml`** me hai: site ka naam, tagline, contact email, AdSense ID, Search Console code.
GitHub par file kholo → ✏️ (edit) → change karo → **Commit changes**. 3–4 minute me site update.

## 3. Full Detail post likhna (sabse zaroori — traffic aur AdSense isi se aata hai)

1. `content/posts/_TEMPLATE.md` kholo, poora content copy karo.
2. **Add file → Create new file** → naam: `content/posts/ssc-gd-2026.md` → paste karo.
3. Official notification PDF padhkar dates, fees, age, vacancy bharo. Neeche "How to apply" **apne shabdon me** likho.
4. Commit karo. Post home page ki "Important" strip aur category box me aa jayega.

`match:` me jo shabd likhoge, wahi shabd jis auto notice ke title me hoga, us notice page par "Full Detail" ka link apne-aap lag jayega.

## 4. Naya official source add karna

`sources.yaml` me koi bhi block copy karo, `id`, `name`, `short`, `url` badlo. Agar page JavaScript se banta hai (khaali dikhta hai) to `js: true` lagao.
Agar page par bahut faltu links aa rahe hain to `selector:` (sirf notice board wala hissa) ya `exclude:` use karo.

## 5. Google AdSense se kamai — honest roadmap

1. **Apna domain lo** (.in / .com, approx ₹600–900/saal). vercel.app subdomain par AdSense approval lagbhag nahi milta.
   Domain lene ke baad Vercel → Settings → Domains me add karo.
2. `config.yaml` me `contact_email` bharo (About, Contact, Privacy, Disclaimer pages pehle se bane hain).
3. **Google Search Console** me site add karo → `google_site_verification` bharo → `sitemap.xml` submit karo.
4. **Kam se kam 25–30 original Full Detail posts** likho. Sirf auto-links wali site ko AdSense "low value content" bolke reject karta hai.
5. 1–2 mahine regular posting ke baad AdSense apply karo. Approve hone par `adsense.client` me `ca-pub-...` daal do —
   script, `ads.txt` aur ad slots apne-aap lag jayenge.

Sach: is field me competition bahut hai. Traffic dheere-dheere aata hai (3–6 mahine), aur sabse zyada fayda **jaldi, sahi aur detailed posts** se hota hai — khaas kar MP/state level ki bhartiyon par, jahan badi sites kam dhyan deti hain.

## Local par chalana (optional)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # sirf js: true wale sources ke liye
python -m scraper.update                # official sites check
python -m builder.build                 # public/ folder me site
python -m http.server -d public 8000    # http://localhost:8000
```

## Folder structure

| Path | Kya hai |
|---|---|
| `config.yaml` | Site settings (naam, AdSense, email) |
| `sources.yaml` | Official websites ki list |
| `content/posts/` | Aapke Full Detail posts |
| `content/pages/` | About, Contact, Privacy, Disclaimer, Terms |
| `data/notices.json` | Robot ka jama kiya data (khud update hota hai) |
| `scraper/` | Official sites se notice nikalne ka code |
| `builder/` | Website banane ka code, templates, CSS |
| `.github/workflows/update.yml` | Har 3 ghante chalne wala robot |
| `vercel.json` | Vercel build settings |

> Har notice ke saath official link diya jata hai. Ye website kisi sarkari vibhag se judi nahi hai.
