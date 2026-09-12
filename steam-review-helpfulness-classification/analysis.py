"""
Steam Review Helpfulness Classification
========================================
Predicting whether a Steam review will be marked "helpful", from the
review text and a few structured signals -- a real review-ranking problem
(the same one platforms like Steam/Amazon solve to decide which reviews to
surface first).

Data
----
6,417,106 real English-language Steam reviews (game_id, review_text,
recommended flag, helpful flag), from the "Steam Review Dataset (2017)" by
Antoni Sobkowicz, National Information Processing Institute -- published on
Zenodo, DOI 10.5281/zenodo.1000885, CC BY-NC 4.0. See download.py for the
exact notebook cells used to pull it directly into a Databricks lakehouse
(the ~500MB raw file and 6.4M-row table never leave Databricks -- this repo
only holds the aggregated results in results.json, produced by the actual
PySpark pipeline).

Method
------
1. EDA revealed `helpful_votes` is a binary flag, not a vote count -- the
   project was originally scoped as regression and pivoted to
   classification once the real schema was confirmed. Class balance:
   14.7% helpful / 85.3% not helpful.
2. Baseline: Logistic Regression on structured features only (review
   length, word count, punctuation, recommended flag) -- AUC 0.578,
   barely better than chance.
3. Added TF-IDF text features (HashingTF + IDF, 2,000 dimensions) --
   AUC jumps to 0.657. The actual words in a review matter far more than
   its surface shape.
4. Hyperparameter tuning (CrossValidator, 3-fold, regParam x
   elasticNetParam grid) -- AUC 0.658, a negligible +0.0004. Honest
   finding: the model wasn't overfitting: the ceiling here is the feature
   set, not the regularization strength.
5. Re-fit with StandardScaler (withMean=False -- mean-centering a sparse
   2,000-dim TF-IDF vector densifies it and blows up cost; scale by
   std-dev only) to get comparable coefficients. `recommended` has the
   strongest single effect (-0.25): critical reviews are more often
   marked helpful than purely positive ones, consistent with published
   review-helpfulness research. `review_length` and `word_count` show
   opposite signs -- a multicollinearity artifact between two features
   that measure almost the same thing, not two real opposing effects.
6. At the default 0.5 threshold, recall on the "helpful" class is only
   ~1.2% (imbalance pulls predictions toward the majority class) even
   though AUC (which measures ranking across all thresholds) is 0.66 --
   the concrete reason AUC alone doesn't tell the whole story, and why a
   production system would rank by predicted probability rather than
   use a hard cutoff.
7. HashingTF trades interpretability for speed/memory: the 2,000 TF-IDF
   coefficients can't be traced back to individual words (hash
   collisions). Only the 5 structured-feature coefficients are reported
   here for that reason.

Reproduce: the heavy pipeline (download, TF-IDF, training, tuning) runs in
a Databricks notebook against the full 6.4M-row dataset -- see download.py
for the exact PySpark cells. This script only re-renders the resulting
metrics (already computed, in results.json) as figures.
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(HERE, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

NAVY, GOLD, RED, GREEN, GREY = "#1a1a2e", "#c8943a", "#a6402f", "#3f7a4a", "#9a9690"
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.facecolor"] = "#faf9f7"
plt.rcParams["figure.facecolor"] = "white"

with open(os.path.join(HERE, "results.json"), encoding="utf-8") as f:
    r = json.load(f)

print("=" * 65)
print("STEAM REVIEW HELPFULNESS CLASSIFICATION -- real Steam review data")
print("=" * 65)
print(f"Reviews: {r['n_reviews']:,}  |  helpful: {r['class_balance']['helpful']:,} "
      f"({100 * r['class_balance']['helpful'] / r['n_reviews']:.1f}%)  |  "
      f"not helpful: {r['class_balance']['not_helpful']:,}")

# =====================================================================
# 1. Class balance
# =====================================================================

fig, ax = plt.subplots(figsize=(6, 5))
labels = ["Not helpful", "Helpful"]
vals = [r["class_balance"]["not_helpful"], r["class_balance"]["helpful"]]
bars = ax.bar(labels, vals, color=[GREY, NAVY])
for bar, v in zip(bars, vals):
    ax.text(bar.get_x() + bar.get_width() / 2, v + max(vals) * 0.01, f"{v:,}\n({100*v/sum(vals):.1f}%)",
             ha="center", fontsize=10, color=NAVY)
ax.set_ylabel("Reviews")
ax.set_title(f"Class balance ({sum(vals):,} real Steam reviews)", color=NAVY)
ax.grid(axis="y", alpha=0.25)
plt.tight_layout()
plt.savefig(f"{FIG_DIR}/class_balance.png", dpi=130, bbox_inches="tight")
plt.close()

# =====================================================================
# 2. AUC progression across the 4 modeling iterations
# =====================================================================

fig, ax = plt.subplots(figsize=(8, 5))
stages = ["Baseline\n(structured only)", "+ TF-IDF\ntext features", "+ Tuned\n(CrossValidator)", "+ Scaled\n(interpretable coefs)"]
aucs = [r["auc"]["baseline"], r["auc"]["tfidf"], r["auc"]["tuned"], r["auc"]["scaled"]]
colors = [GREY, GOLD, NAVY, NAVY]
bars = ax.bar(stages, aucs, color=colors)
for bar, v in zip(bars, aucs):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.4f}", ha="center", fontsize=10, color=NAVY)
ax.axhline(0.5, color=RED, linestyle="--", linewidth=1.2, label="Random guessing (AUC = 0.5)")
ax.set_ylabel("AUC-ROC")
ax.set_ylim(0.45, 0.75)
ax.set_title("Model iteration: where the signal actually came from", color=NAVY)
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.25)
plt.tight_layout()
plt.savefig(f"{FIG_DIR}/auc_progression.png", dpi=130, bbox_inches="tight")
plt.close()

# =====================================================================
# 3. Confusion matrix (default 0.5 threshold) -- the recall problem
# =====================================================================

cm = r["confusion_matrix"]
matrix = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
fig, ax = plt.subplots(figsize=(6, 5.5))
im = ax.imshow(matrix, cmap="Blues")
ax.set_xticks([0, 1]); ax.set_xticklabels(["Pred: Not helpful", "Pred: Helpful"])
ax.set_yticks([0, 1]); ax.set_yticklabels(["Actual: Not helpful", "Actual: Helpful"])
for i in range(2):
    for j in range(2):
        ax.text(j, i, f"{matrix[i, j]:,}", ha="center", va="center",
                 color="white" if matrix[i, j] > matrix.max() / 2 else NAVY, fontsize=12)
recall = cm["tp"] / (cm["tp"] + cm["fn"])
precision = cm["tp"] / (cm["tp"] + cm["fp"])
ax.set_title(f"Confusion matrix @ 0.5 threshold\nRecall (helpful): {recall*100:.1f}%  |  Precision: {precision*100:.1f}%", color=NAVY)
plt.tight_layout()
plt.savefig(f"{FIG_DIR}/confusion_matrix.png", dpi=130, bbox_inches="tight")
plt.close()

print(f"\nAt the default 0.5 threshold: recall on 'helpful' = {recall*100:.1f}%, precision = {precision*100:.1f}%")
print("(AUC measures ranking across ALL thresholds -- this is why a fixed 0.5 cutoff alone is misleading under class imbalance.)")

# =====================================================================
# 4. Structured-feature coefficients (scaled model -- comparable units)
# =====================================================================

coefs = r["coefficients"]
names = list(coefs.keys())
values = list(coefs.values())
order = np.argsort(values)
names = [names[i] for i in order]
values = [values[i] for i in order]
colors = [RED if v < 0 else GREEN for v in values]

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.barh(names, values, color=colors)
span = max(values) - min(values)
for bar, v in zip(bars, values):
    ax.text(v + (0.02 * span if v >= 0 else -0.02 * span), bar.get_y() + bar.get_height() / 2, f"{v:+.4f}",
             va="center", ha="left" if v >= 0 else "right", fontsize=9, color=NAVY)
ax.axvline(0, color=GREY, linewidth=0.8)
ax.set_xlim(min(values) - 0.28 * span, max(values) + 0.22 * span)
ax.set_xlabel("Standardized coefficient (Logistic Regression, scaled features)")
ax.set_title("What predicts helpfulness -- structured features only\n(2,000 TF-IDF dims omitted: HashingTF hashes words, not individually traceable)", color=NAVY, fontsize=10)
plt.tight_layout()
plt.savefig(f"{FIG_DIR}/coefficients.png", dpi=130, bbox_inches="tight")
plt.close()

print("\nDone. Figures in ./figures")
print(f"Strongest single effect: 'recommended' ({coefs['recommended']:+.4f}) -- "
      f"critical reviews are more often marked helpful than purely positive ones.")
