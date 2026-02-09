# 🤖 Multi-Agent PR Review (Private Agent)

Private repo'dan cross-repo PR review sistemi.

---

## 🔄 Akış

```
┌─────────────────┐     trigger      ┌──────────────────┐
│  PUBLIC REPO    │ ──────────────▶  │  PRIVATE REPO    │
│  (Proje kodu)   │                  │  (Bu repo/Agent) │
│                 │  ◀────────────── │                  │
│  PR'a yorum     │     comment      │  6 AI Agent      │
└─────────────────┘                  └──────────────────┘
```

---

## 🚀 Kurulum

### ADIM 1: GCP Service Account

```bash
# Service Account oluştur
gcloud iam service-accounts create github-pr-reviewer \
  --display-name="GitHub PR Reviewer" \
  --project=YOUR_PROJECT_ID

# Vertex AI User rolü ver
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-pr-reviewer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# JSON key oluştur
gcloud iam service-accounts keys create github-sa-key.json \
  --iam-account=github-pr-reviewer@YOUR_PROJECT_ID.iam.gserviceaccount.com

# Vertex AI API aktif et
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
```

### ADIM 2: GitHub PAT Oluştur

GitHub → Settings → Developer settings → Fine-grained tokens:

**Yetkileri:**
- Repository access: Agent repo + Public repo seç
- Actions: Read and write
- Contents: Read  
- Pull requests: Read and write

### ADIM 3: Bu Repo'ya Secrets Ekle

| Secret | Değer |
|--------|-------|
| `GCP_SA_KEY` | Service Account JSON (tamamı) |
| `GCP_PROJECT_ID` | GCP proje ID |
| `GH_PAT` | Oluşturduğun GitHub PAT |

### ADIM 4: Public Repo'ya Workflow Ekle

Public repo'da `.github/workflows/trigger-review.yml`:

```yaml
name: Trigger AI Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Agent Review
        env:
          GH_TOKEN: ${{ secrets.AGENT_PAT }}
        run: |
          gh workflow run pr-review.yml \
            --repo YOUR_USERNAME/WBTS-Hackhathon \
            --field target_repo=${{ github.repository }} \
            --field pr_number=${{ github.event.pull_request.number }}
```

### ADIM 5: Public Repo'ya Secret Ekle

| Secret | Değer |
|--------|-------|
| `AGENT_PAT` | Aynı GitHub PAT |

---

## ✅ Test

1. Public repo'da branch oluştur
2. Değişiklik yap, commit, push
3. PR aç
4. Actions tab'larını izle:
   - Public repo: `Trigger AI Review` çalışır
   - Private repo: `AI PR Review` çalışır
5. PR'da AI yorumunu gör

---

## 🤖 6 AI Agent

| Agent | Görev |
|-------|-------|
| 🎯 Product Owner | User story validation |
| 👨‍💻 Senior Engineer | Code quality |
| 🔒 Security Engineer | Security check |
| 🔧 DevOps Engineer | CI/CD review |
| 🧪 QA Engineer | Test coverage |
| 🎖️ Tech Lead | Final decision |

---

## 📁 Dosya Yapısı

```
WBTS-Hackhathon/           (Private)
├── .github/workflows/
│   └── pr-review.yml      # Dispatch ile tetiklenen workflow
├── multi_agent_reviewer.py
├── requirements.txt
└── README.md

your-public-repo/          (Public)
├── .github/workflows/
│   └── trigger-review.yml # PR'da agent'ı tetikler
└── ... (proje dosyaları)
```

---

## 🔍 Sorun Giderme

| Hata | Çözüm |
|------|-------|
| `Workflow not found` | Private repo'da Actions aktif mi? |
| `Resource not accessible` | PAT yetkileri doğru mu? |
| `Permission denied` | GCP Service Account'a rol verildi mi? |

---

## 📄 License

MIT
