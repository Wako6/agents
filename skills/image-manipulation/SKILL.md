---
name: image-manipulation
description: Manipulation d images pour un projet. Use quand Codex doit recadrer une image, la redimensionner, generer une miniature, convertir un format (png, jpg, webp, avif) ou preparer un asset image avant de l inserer dans le projet.
---

# Image Manipulation

## Overview

Utiliser ce skill quand une image doit etre preparee avant integration dans le projet.
Le workflow standard repose sur `scripts/image_ops.py`, qui encapsule `ImageMagick` pour les operations les plus frequentes.

## Workflow

1. Identifier le fichier source et le format de sortie attendu par le projet.
2. Choisir l operation:
   - `resize` pour adapter une image a une boite donnee.
   - `crop` pour extraire une zone precise.
   - `convert` pour changer de format ou ajuster la qualite.
   - `thumbnail` pour produire une miniature prete a l emploi.
3. Executer `python3 scripts/image_ops.py ...` depuis le dossier du skill ou via le chemin absolu.
4. Verifier le resultat avec `magick identify <fichier>` ou en ouvrant l image si necessaire.
5. Inserer ensuite le fichier genere dans le projet avec un nom explicite et stable.

## Command Patterns

### Resize

Utiliser pour adapter une image a une largeur/hauteur cibles.

```bash
python3 scripts/image_ops.py resize INPUT OUTPUT --width 1600 --height 900 --mode fit
```

Modes disponibles:
- `fit`: conserve les proportions et rentre dans la boite.
- `fill`: remplit la boite puis centre/coupe.
- `stretch`: force exactement la taille demandee.

### Crop

Utiliser quand le cadrage doit etre controle manuellement.

```bash
python3 scripts/image_ops.py crop INPUT OUTPUT --width 800 --height 800 --x 120 --y 60
```

### Convert

Utiliser pour passer de `png` vers `jpg`, `webp`, `avif`, etc.

```bash
python3 scripts/image_ops.py convert INPUT OUTPUT.webp --quality 82
```

### Thumbnail

Utiliser pour produire des miniatures ou cartes de listing.

```bash
python3 scripts/image_ops.py thumbnail INPUT OUTPUT.webp --size 480x320 --mode fill --quality 80
```

## Important Rules

- Toujours produire un nouveau fichier de sortie. Ne pas ecraser la source sauf demande explicite.
- Conserver `--mode fit` pour les visuels qui ne doivent pas etre coupes.
- Preferer `--mode fill` pour les miniatures homogenes dans une grille.
- Pour une sortie `jpg` ou `jpeg`, definir `--background` si la source contient de la transparence.
- Le script applique `-auto-orient` et `-strip` par defaut pour eviter les rotations EXIF et nettoyer les metadonnees.
- Si le projet impose des dimensions ou un poids cible, verifier ensuite le resultat avec `magick identify`.

## When To Bypass The Script

Lire directement la doc `magick` et construire une commande specifique uniquement si:
- il faut ajouter du texte, des filtres ou des composites complexes;
- il faut gerer un lot d images avec une logique speciale;
- il faut une optimisation format-specifique plus fine que `--quality`.
