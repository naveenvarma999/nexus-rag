<p align="center">
  <img src="./neural-banner.gif" alt="Naveen Varma — Turning complexity into intelligence. A rotating 3D neural field and an animated Data → Model → Evaluate → Deploy pipeline." width="1120">
</p>

<h1 align="center">Hi, I'm Naveen Varma.</h1>

<p align="center">
  <a href="https://github.com/naveenvarma999">
    <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=500&size=20&duration=2800&pause=900&color=B5F5D2&center=true&vCenter=true&width=640&lines=ML+Engineer+who+ships+models+to+production;Two-tower+recommenders+%C2%B7+fraud+detection+%C2%B7+vision;MLflow+%C2%B7+Docker+%C2%B7+FastAPI+%C2%B7+AWS;Open+to+ML+Engineer+and+MLOps+roles+in+the+UK" alt="ML Engineer who ships models to production. Open to ML Engineer and MLOps roles in the UK.">
  </a>
</p>

<p align="center">
  MSc Applied Data Science · University of Essex · Colchester, UK · <b>Open to ML Engineer roles</b>
</p>

<p align="center">
  <a href="https://www.linkedin.com/in/naveenvarma000/"><img src="https://img.shields.io/badge/LinkedIn-Connect-101B20?style=for-the-badge&amp;logo=linkedin&amp;logoColor=B5F5D2" alt="Connect on LinkedIn"></a>
  <a href="mailto:naveennallapu750@gmail.com"><img src="https://img.shields.io/badge/Email-Let%27s_talk-101B20?style=for-the-badge&amp;logo=gmail&amp;logoColor=B5F5D2" alt="Email Naveen"></a>
  <a href="https://leetcode.com/u/naveenvarma999/"><img src="https://img.shields.io/badge/LeetCode-Problem_solving-101B20?style=for-the-badge&amp;logo=leetcode&amp;logoColor=B5F5D2" alt="LeetCode profile"></a>
  <a href="https://threadline-naveen.duckdns.org"><img src="https://img.shields.io/badge/Live_demo-Threadline-B5F5D2?style=for-the-badge&amp;logo=amazonaws&amp;logoColor=101B20" alt="Threadline live demo"></a>
</p>

<p align="center">
  <a href="#github-pulse">Pulse</a> &nbsp;/&nbsp;
  <a href="#featured-work">Work</a> &nbsp;/&nbsp;
  <a href="#background">Background</a> &nbsp;/&nbsp;
  <a href="#toolkit">Toolkit</a> &nbsp;/&nbsp;
  <a href="https://naveenvarma999.github.io/naveenvarma999/">Live dashboard ↗</a>
</p>

---

## GitHub pulse

<a href="https://naveenvarma999.github.io/naveenvarma999/"><img src="./analytics/profile-pulse.svg" alt="Current contribution streak, longest streak, total contributions, active days and the last 7 days. Updated daily." width="100%"></a>

<a href="https://naveenvarma999.github.io/naveenvarma999/"><img src="./analytics/profile-calendar.svg" alt="Full-year contribution calendar with the longest streak outlined in gold and today marked." width="100%"></a>

<p align="center"><a href="https://naveenvarma999.github.io/naveenvarma999/"><b>Open the interactive GitHub Observatory →</b></a> &nbsp;·&nbsp; <sub>achievements · streak timeline · repo explorer · live commit feed · 3D view</sub></p>

## Featured work

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="https://github.com/naveenvarma999/threadline"><img src="./assets/card-threadline.svg" alt="Threadline: two-stage fashion recommender. 2.5x MAP@12 over a popularity baseline, 76 ms p50 latency, 6 Docker services on AWS." width="100%"></a>
      <p align="center"><a href="https://threadline-naveen.duckdns.org"><b>Live demo</b></a> · <a href="https://github.com/naveenvarma999/threadline">Code</a></p>
    </td>
    <td width="50%" valign="top">
      <a href="https://github.com/naveenvarma999/fraudguard"><img src="./assets/card-fraudguard.svg" alt="FraudGuard: behavioural fraud detection. 0.550 average precision on unseen accounts, Brier score cut by 70%, 128 automated tests." width="100%"></a>
      <p align="center"><a href="https://github.com/naveenvarma999/fraudguard"><b>Code</b></a></p>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center" valign="top">
      <img src="./assets/card-pneumonia.svg" alt="Pneumonia AI: MSc dissertation. ResNet50 with test-time augmentation, ROC-AUC 0.962, sensitivity 0.954, accuracy 0.888." width="50%">
      <p align="center"><sub>MSc dissertation · University of Essex</sub></p>
    </td>
  </tr>
</table>

<details>
<summary><b>How Threadline works</b> (click to expand)</summary>

```mermaid
flowchart LR
    U[React storefront] --> D[Django REST API + PostgreSQL]
    D --> F[FastAPI inference service<br/>p50 76 ms · cache + fallback]
    F --> R[Two-tower retrieval<br/>PyTorch + FAISS]
    R --> K[Gradient-boosting ranker<br/>38 point-in-time features]
    M[(MLflow Model Registry)] -. versions & promotes .-> F
    CI[GitHub Actions · 33 tests] -. deploys .-> AWS[AWS EC2 · 6 Docker services · HTTPS]
```

- **2.5× MAP@12** over a popularity baseline (0.128 vs 0.052), trained on 277K transactions
- Leakage-free, time-based validation; an ablation showed deep-learning features added under 1%
- Angular dashboard for model monitoring

</details>

<details>
<summary><b>How FraudGuard ships models safely</b> (click to expand)</summary>

```mermaid
flowchart LR
    T[Transactions] --> I[Duplicate-safe ingestion]
    I --> S[Production model scores]
    I --> C[Candidate model<br/>shadow scoring]
    L[Analyst labels] --> RT[Label-based retraining] --> C
    C --> G{Promotion gate<br/>unseen-account AP}
    G -- better --> A[Admin approval] --> S
    G -- worse --> K[Keep production model]
```

- **0.550 AP on unseen accounts** (95% bootstrap CI 0.426–0.653) across 523K transactions and 1,197 accounts
- Brier score cut **70%** through calibration; rollback in one step
- AWS EC2 with HTTPS, MFA and rate limiting · **128 automated tests**

</details>

<img src="./analytics/profile-recent.svg" alt="Most recently updated repositories and language mix across public repositories. Updated daily." width="100%">

## About me

[![Naveen Varma — ML engineer and Python developer. MSc Applied Data Science, University of Essex.](./cinematic-depth.gif)](https://www.linkedin.com/in/naveenvarma000/)

I build ML systems end to end: leakage-free validation, honest metrics, then tested and monitored deployment. More in [Introduction](./chapter-1.png) · [Skills](./chapter-2.png) · [Approach](./chapter-3.png).

## Background

<img src="./assets/journey-flow.svg" alt="Career flow: Data Scientist Intern at AI Variant, Hyderabad (Jun to Dec 2024), certifications in SQL (Advanced), Machine Learning A-Z and Deep Learning A-Z, MSc Applied Data Science at the University of Essex (Sep 2025 to present), next: ML Engineer." width="100%">

<p align="center"><sub>Verify certificates: <a href="https://www.hackerrank.com/certificates/e40a41d63714">SQL (Advanced) ↗</a> &nbsp;·&nbsp; <a href="https://ude.my/UC-229fbddb-ee70-42c9-87e0-dee06780397b">Machine Learning A-Z ↗</a> &nbsp;·&nbsp; <a href="https://ude.my/UC-3bbf72ed-39f4-49fc-9897-5d8291ac87c6">Deep Learning A-Z ↗</a></sub></p>

## Toolkit

### Languages & data

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python" height="28">
  <img src="https://img.shields.io/badge/SQL-336791?style=for-the-badge" alt="SQL" height="28">
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&amp;logo=postgresql&amp;logoColor=white" alt="PostgreSQL" height="28">
  <img src="https://img.shields.io/badge/Pandas-150458?style=for-the-badge&amp;logo=pandas&amp;logoColor=white" alt="Pandas" height="28">
  <img src="https://img.shields.io/badge/NumPy-013243?style=for-the-badge&amp;logo=numpy&amp;logoColor=white" alt="NumPy" height="28">
</p>

### Machine learning

<p>
  <img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&amp;logo=pytorch&amp;logoColor=white" alt="PyTorch" height="28">
  <img src="https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&amp;logo=scikitlearn&amp;logoColor=white" alt="scikit-learn" height="28">
  <img src="https://img.shields.io/badge/TensorFlow-FF6F00?style=for-the-badge&amp;logo=tensorflow&amp;logoColor=white" alt="TensorFlow" height="28">
  <img src="https://img.shields.io/badge/Keras-D00000?style=for-the-badge&amp;logo=keras&amp;logoColor=white" alt="Keras" height="28">
  <img src="https://img.shields.io/badge/FAISS-0467DF?style=for-the-badge&amp;logo=meta&amp;logoColor=white" alt="FAISS" height="28">
</p>

### Applications & serving

<p>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&amp;logo=fastapi&amp;logoColor=white" alt="FastAPI" height="28">
  <img src="https://img.shields.io/badge/Django-092E20?style=for-the-badge&amp;logo=django&amp;logoColor=white" alt="Django" height="28">
  <img src="https://img.shields.io/badge/Flask-232F3E?style=for-the-badge&amp;logo=flask&amp;logoColor=white" alt="Flask" height="28">
  <img src="https://img.shields.io/badge/React-20232A?style=for-the-badge&amp;logo=react&amp;logoColor=61DAFB" alt="React" height="28">
  <img src="https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&amp;logo=streamlit&amp;logoColor=white" alt="Streamlit" height="28">
</p>

### Engineering & MLOps

<p>
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&amp;logo=docker&amp;logoColor=white" alt="Docker" height="28">
  <img src="https://img.shields.io/badge/AWS_EC2-232F3E?style=for-the-badge&amp;logo=amazonaws&amp;logoColor=white" alt="AWS EC2" height="28">
  <img src="https://img.shields.io/badge/MLflow-0194E2?style=for-the-badge&amp;logo=mlflow&amp;logoColor=white" alt="MLflow" height="28">
  <img src="https://img.shields.io/badge/GitHub%20Actions-2088FF?style=for-the-badge&amp;logo=githubactions&amp;logoColor=white" alt="GitHub Actions" height="28">
  <img src="https://img.shields.io/badge/Git-F05032?style=for-the-badge&amp;logo=git&amp;logoColor=white" alt="Git" height="28">
  <img src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&amp;logo=linux&amp;logoColor=black" alt="Linux" height="28">
</p>

### Analysis & visualization

<p>
  <img src="https://img.shields.io/badge/Tableau-E97627?style=for-the-badge" alt="Tableau" height="28">
  <img src="https://img.shields.io/badge/Matplotlib-11557C?style=for-the-badge" alt="Matplotlib" height="28">
</p>

---

<p align="center">
  <b>Now:</b> finishing my MSc dissertation and looking for ML Engineer and MLOps roles in the UK.<br>
  <sub>Curiosity drives the experiment. Evidence earns the conclusion. · Panels on this page are generated daily from my public GitHub activity.</sub>
</p>
