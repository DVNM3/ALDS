<h1 align="center">ALDS</h1>

<p align="center">
  Turn anime episodes into a clean, captioned LoRA dataset for one character.<br>
  Made for training <b>Anima</b> LoRAs in <b>AI Toolkit</b>, with an Arabic and English interface.
</p>

<p align="center">
  <a href="https://github.com/DVNM3/ALDS/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/DVNM3/ALDS"></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-blue">
  <img alt="Windows" src="https://img.shields.io/badge/platform-Windows-lightgrey">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

<p align="center">
  <a href="https://dvnm3.github.io/ALDS/">Project page</a> ·
  <a href="#installing">Install</a> ·
  <a href="#using-the-interface">Usage</a> ·
  <a href="#command-line">Command line</a> ·
  <a href="https://github.com/DVNM3/ALDS/releases">Releases</a>
</p>

![The review tab](docs/screenshots/review.png)

Making a character LoRA from an anime usually means hours of taking screenshots, cropping, sorting and writing captions. ALDS does it from the episode files: it finds every character in the episodes, lets you pick yours, and builds a sorted, captioned image set that you review in a few minutes and train on.

## Features
- **Finds your character.** Every character in the episodes is detected and grouped by identity, so you pick yours with one click. A few reference images work too, which helps with side characters.
- **Skips the opening and ending.** The OP/ED and long recaps are found by comparing the episodes with each other, and left out.
- **Three crops per shot.** Whole body, upper body and head, each one checked again to be the right character.
- **Leaves out other characters.** The clusters you didn't pick show what the other characters look like, so images that resemble one of them more than yours are left out before you review.
- **Filters out bad images.** On-screen text, dark or faded frames, black-and-white or sepia flashbacks, other characters in the way, chibi and blurry drawings, and near-duplicates.
- **Captions in Anima's style.** WD14 tags in Anima's order with your trigger word. Fixed features such as hair and eye colour are left to the trigger word.
- **Sorted by shot and angle.** From close-up to full body, and front, three-quarter, side, back, from above and from below.
- **Separates outfits.** When the character wears more than one outfit, each outfit gets its own tag.
- **Learns from your review.** Reject an image as another character, and every image like it is flagged and left out of later builds.
- **Anime upscaler (optional).** Small crops are enlarged with a model made for anime instead of being thrown away.
- **Fast rebuilds.** The analysis is saved, so trying other thresholds or options takes seconds instead of minutes.
- **Safe to stop.** Every long action can be stopped, and whatever it made is removed.
- **Ready for AI Toolkit.** From the command line, export can balance the angles and write a job config with the step schedule worked out for your image count.

## Screenshots
Pictures taken from the episodes are blurred here; in the program they show as they are.

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="docs/screenshots/pick.png"><img src="docs/screenshots/pick.png" alt="Pick the character"></a>
      <br><b>Pick the character.</b> Every character found in the episodes gets a card. Click yours, type a trigger word and build the image set.
    </td>
    <td width="50%" valign="top">
      <a href="docs/screenshots/tags.png"><img src="docs/screenshots/tags.png" alt="Tag editor"></a>
      <br><b>Tags.</b> Every tag in the captions with its count. Search, then remove, replace or add a tag in all captions at once, with undo.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="docs/screenshots/save.png"><img src="docs/screenshots/save.png" alt="Save the result"></a>
      <br><b>Save the result.</b> A summary before saving: the outfits, the upscaled images and the shot and angle distribution.
    </td>
    <td width="50%" valign="top">
      <a href="docs/screenshots/review-ar.png"><img src="docs/screenshots/review-ar.png" alt="Arabic interface"></a>
      <br><b>Arabic interface.</b> The same page right to left, one button away.
    </td>
  </tr>
</table>

## Requirements
- Windows 10 or 11 and [Python 3.12](https://www.python.org/downloads/).
- An NVIDIA graphics card with CUDA is strongly recommended. The program runs on the processor alone, but slowly. A scan uses up to about 8 GB of graphics memory.
- Free disk space: the extracted frames take a few hundred megabytes per episode until you clean them up.
- [AI Toolkit](https://github.com/ostris/ai-toolkit) to train the LoRA afterwards.

## Installing
1. Download the ZIP of the [latest release](https://github.com/DVNM3/ALDS/releases/latest) and extract it, or clone the repository:
   ```bat
   git clone https://github.com/DVNM3/ALDS.git
   ```
2. In the program folder, create the Python environment and install the requirements:
   ```bat
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Double-click **`alds-gui.bat`**. The models download from Hugging Face by themselves on the first run.

**Updating:** run `git pull` in the program folder, or replace the `alds` folder with the one from the new ZIP. Your `projects` folder, `settings.json` and `.venv` stay as they are. If `requirements.txt` changed, run the `pip install` line again.

## Using the interface
Double-click **`alds-gui.bat`**. The interface opens in your browser at `http://127.0.0.1:7860` and only runs on your computer. To stop it, close the black command window.

The **العربية / English** button at the top switches the language in place, without losing anything you did on the page. The language you used last opens on the next start.

The tabs follow the work from left to right:

| Tab | What you do there |
|---|---|
| **1. Scan episodes** | Paste episode paths, or the path of a whole folder, and press “Start scanning”. The OP/ED is found automatically and its times show in the episodes table. “💾 Disk space” shows the project's size and cleans it up. |
| **2. Pick the character** | Click your character's card (you can pick more than one) or upload reference images, type the trigger word and press “Build the image set”. If two characters got mixed in one card, select it and press “✂ Split”. |
| **3. Review** | Opens by itself after a build, with the images marked ⚠ first. Remove what isn't right, fix a caption, move an image to another group, or show one outfit only. |
| **4. Tags** | Every tag and how often it appears. Remove, replace or add a tag in all captions at once, with undo. |
| **5. Save the result** | Choose a place; a folder named after the character is made there with the images and their caption files. That folder is your dataset. Afterwards you can delete the project to free space. |

Review keys:

| Key | Action |
|---|---|
| **N** | Not this character: an image of another character. The program learns from it and leaves out what looks like it from now on. |
| **Delete** | Bad image of the character itself. It's only removed. |
| **← →** | Previous and next image. |
| **Ctrl+Z** | Undo the last removal. |

- **Stop button:** every long action shows one while it runs. The action stops within seconds and the project is back exactly as it was. The same happens when an action fails, and with **Ctrl+C** on the command line.
- Removed images aren't deleted for good: they move to a `_deleted` folder inside the character folder.

## Where your files go
Everything the program makes stays in the `projects` folder next to it, one folder per project:

```
projects\<project>\
  frames\        extracted frames (the biggest part; free it with "clean")
  clusters\      the character cards and sheets
  cache\         saved analysis that makes rebuilds fast
  characters\<name>\
    sorted\close_up\front\ ...   a PNG image + a .txt caption, sorted by shot and angle
    sorted\_review\ ...          doubtful images to check first
    report.txt                   statistics and the angle distribution
```

“Save the result” (or `export` on the command line) copies the reviewed images and captions into one flat folder: the dataset you point AI Toolkit at, with caption extension `txt`.

## How a build works
| Stage | How |
|---|---|
| Recognising the character | CCIP compares every detected character with the references; the default threshold is 0.13. |
| Other characters | Images from the clusters you didn't pick that don't look like your character are used to leave out frames closer to another character than to yours (`--no-auto-reject` turns it off). |
| Cropping | Three crops: the whole body, the upper body and the head. Every head or upper-body crop is checked for identity again. |
| Leaving out | Text on screen (read with OCR), dark or faded frames, black-and-white or sepia flashbacks (`--keep-mono` keeps them), another character overlapping, chibi and blurry drawings. |
| Removing duplicates | Visual similarity (WD14 embedding) ≥ 0.80; the sharpest image is kept. |
| Tags | WD14 EVA02-Large, in Anima's style: lowercase, spaces instead of `_`. |
| Caption order | `anime screencap, safe, 1boy, <trigger>, <series>, <tags...>` |
| Fixed features | Hair and eye colours and the hairstyle are removed from the captions so the trigger word learns them (`--keep-core` keeps them). |
| Angle | Tags give side, back, from above and from below; where the eyes sit inside the face separates three-quarter from front. |
| Outfits | Body crops grouped by their clothing tags and how they look, with a tag per outfit when there is more than one. |
| Upscaling (optional) | Every image smaller than 1024 pixels is enlarged with the CDC anime upscaler, at most 4×. |

## Command line
Everything in the interface is also available as commands, plus balancing and AI Toolkit job configs on export.

```
scan  →  pick the character's number  →  build  →  review  →  export
```

| Command | What it does |
|---|---|
| `scan` | Extract frames, find the characters and group them into numbered clusters. |
| `autoskip` | Find the OP/ED again, or turn it off with `--off`. |
| `clusters` / `split` | Re-cluster the project, or split one mixed cluster. |
| `build` | Make the character's sorted, captioned images. |
| `reject` | Mark images as another character, or list the ones that look like rejected images. |
| `tags` / `outfits` | Edit tags in bulk; separate the outfits again. |
| `export` | Copy the reviewed images into one dataset folder, optionally balanced, with an AI Toolkit config. |
| `clean` | Free disk space. |
| `gui` | Open the interface. |

`alds.bat <command> --help` lists every option of a command.

### scan
```bat
alds.bat scan -p fairytail "D:\anime\ep01.mkv" "D:\anime\ep02.mkv"
```
- A whole folder works instead of files. Running `scan` again on the same project adds new episodes.
- **OP/ED:** every part repeated between episodes for 40 seconds or more is left out. With a single episode, the next episode in the same folder is used for the comparison, without extracting anything from it. `--no-auto-skip` turns it off, `--auto-min 60` changes the length, and `--skip 0:00-1:30` ignores more times by hand.
- The result is `projects\<p>\clusters\overview.jpg`, with a row per character and its number. **Cluster numbers change after every scan.**
- `alds.bat split -p fairytail --cluster 3` splits a cluster where similar characters got mixed; the other clusters keep their numbers. `--cut 0.10` splits harder.

### build
```bat
alds.bat build -p fairytail -n natsu_ft --cluster 2 --series "fairy tail"
```
- `-n` is the trigger word, also the name of the character folder.
- `--cluster 2 5` when the character is split over more than one cluster; `--ref folder` for 3 to 10 reference images instead of, or as well as, cluster numbers.
- Building again with other settings only analyses what's new; `--fresh` redoes everything.

### review
In the interface, or by hand: open the `sorted` folder and delete every image that isn't the character, starting with `_review`. The `.txt` captions can be edited too.

```bat
alds.bat reject -p fairytail -n natsu_ft v01_00616.0s_full.png
alds.bat tags -p fairytail -n natsu_ft --remove parody --replace "yellow eyes=brown eyes"
alds.bat tags -p fairytail -n natsu_ft --undo
alds.bat outfits -p fairytail -n natsu_ft
```
- `reject` learns an image as another character and lists the ones that look like it; `--clear` forgets all rejections.
- `tags` without options lists every tag and its count. Outfit tags can be renamed with a replace, such as `natsu_ft_outfit1=natsu_ft_coat`.
- `outfits` separates the outfits again after images were removed; `--no-outfits` on `build` skips them.

### export
```bat
alds.bat export -p fairytail -n natsu_ft --total 100
```
Copies the images and captions into one folder, `train\`.
- `--total 100` balances the angles: the count is spread over the angle folders by the square root of their size, and the picks inside each folder are varied but typical. `--max-per-group 15` caps each folder instead.

**Straight into AI Toolkit, with a job config:**
```bat
alds.bat export -p fairytail -n natsu_ft --total 60 --aitk "E:\AI-Toolkit-Easy-Install\AI-Toolkit" --dataset-name natsu_dragneel
```
- The images go to `AI-Toolkit\datasets\natsu_dragneel\`. The AI Toolkit path is remembered, so later `--aitk` alone is enough.
- The job config is made from `ALDS\aitk_template.yaml` and saved in the character folder and in `AI-Toolkit\config\`. In AI Toolkit, create a new job and paste it in Advanced mode.
- The schedule is worked out from the number of exported images:
  - `Save Every = Sample Every = round(images × resolutions × 10 ÷ 4)`
  - `Steps = Save Every × (epochs ÷ 10)`
  - `Max Saves = epochs ÷ 10`
  - Batch 1, gradient accumulation 4, warmup 100.
- `--epochs 50` or `60` instead of 40, and `--res 512 1024` for the resolutions.
- The job name gets the next free version (`Natsu_Dragneel_v1`, `v2`, ...), and the sample prompts use `1girl` or `1boy` to match the character, with one prompt per outfit.
- A dataset folder the program didn't make is never overwritten. To change the fixed training settings (network, learning rate, EMA, negative prompt...), edit `ALDS\aitk_template.yaml`.

### clean
```bat
alds.bat clean -p fairytail
alds.bat clean -p fairytail --all
```
- **Without `--all`:** deletes the frames the program will never read again (inside the OP/ED or without characters), the thumbnails, and unused images in `cache`. Building and clustering keep working.
- **With `--all`:** deletes every frame and the saved analysis. The finished images stay, but the project can't be built or clustered any more.

## Tuning
- `report.txt` shows how the match scores are spread. If other characters slip in, lower `--threshold` (e.g. 0.11); if there are too few images, raise it (e.g. 0.15).
- `--sim 0.85` keeps more similar images; `0.75` removes duplicates more strictly.
- `--min-size 512` rejects small crops. The default is 448 (the square root of the area), or 320 with `--upscale`.
- `--upscale --upscale-to 768` upscales to your training resolution.
- `--save-dropped` keeps the left-out images in `_dropped\<reason>\`, to check the filters.
- `--overwrite` builds again and **clears** the `sorted` folder, and your review with it.

## Built with
- [imgutils](https://github.com/deepghs/imgutils) by deepghs: character detection, CCIP identity features, OCR, the CDC upscaler and the WD14 tagger interface.
- [WD14 taggers](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) by SmilingWolf for the tags.
- [Gradio](https://www.gradio.app/) for the interface, [PyAV](https://github.com/PyAV-Org/PyAV) for decoding and [scikit-learn](https://scikit-learn.org/) for clustering.

## License
MIT, see [LICENSE](LICENSE).
