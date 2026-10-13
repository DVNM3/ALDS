# animelora

Turns anime episodes into a ready-to-train image set for a LoRA of one character (set up for Anima and AI Toolkit).

## Installing
```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
The models download from HuggingFace by themselves on the first run.

## Graphical interface
Double-click **`animelora-gui.bat`**. The interface opens in your browser at `http://127.0.0.1:7860`. To stop it, close the black command window.

**Language:** the interface comes in Arabic (right to left, `http://127.0.0.1:7860/`) and English (`http://127.0.0.1:7860/en`). Switch with the **Arabic | English** links at the top of the page; the language you used last opens on the next start.

| Tab | What you do there |
|---|---|
| 1. Scan episodes | Paste episode paths (or a whole folder), then press “Start scanning”. The OP/ED is found automatically and its times show in the episodes table. “💾 Disk space” shows the project's size and cleans it up |
| 2. Pick the character | Click a character's card to select it (you can select more than one) or upload reference images, type the trigger word, then “Build the image set”. If two characters got mixed in one card, select it and press “✂ Split” |
| 3. Review | Opens by itself after a build. Images marked ⚠ come first. **N** for an image of another character (the program learns from it), **Delete** for a bad image of the character itself, **← →** to move, **Ctrl+Z** to undo. You can also edit a caption, move an image that was put in the wrong group, or show one outfit only |
| 4. Tags | A table of all tags and how often they appear. Remove, replace or add a tag in **all** captions at once, with undo |
| 5. Save the result | Paste the path of the place you want; a folder named after the character is made there with the images and caption files. The last place is remembered, and saving inside the projects folder or over a folder the program didn't make is refused. A summary shows the image count, outfits, angle distribution, and a warning if images are still waiting for review. After saving you can delete the whole project from the program folder to free space |

- **Stop button:** shows under the button of every long action while it runs. The action stops within seconds, everything it generated is removed, and the project is exactly as it was before. The same happens when an action fails with an error. On the command line **Ctrl+C** works the same way.
- Deleted images move to a `_deleted` folder inside the character folder.
- The interface only runs on your computer (127.0.0.1).

## Command line

```
scan  →  pick the character's number from the image  →  build  →  review the images  →  export
```

### 1) scan: extract frames, find the characters, cluster them
```bat
animelora.bat scan -p fairytail "D:\anime\ep01.mkv" "D:\anime\ep02.mkv"
```
- You can give it a whole folder instead of files.
- **The OP/ED is found automatically:** the episodes are compared with each other and every part repeated for 40 seconds or more is left out. With a single episode, the next episode in the same folder is used for the comparison, without extracting anything from it.
  - To turn it off: `--no-auto-skip`. To change the shortest length: `--auto-min 60`.
- `--skip 0:00-1:30`: more times to ignore by hand.
- Running `scan` again on the same project adds new episodes.
- `animelora.bat autoskip -p fairytail`: finds the OP/ED again for the scanned episodes. With `--off` every frame is used.
- The result: `projects\<p>\clusters\overview.jpg`, with a row per character and its number (#1, #2 ...). **Cluster numbers change after every scan.**
- `animelora.bat split -p fairytail --cluster 3`: splits a cluster where similar characters got mixed. The other clusters keep their numbers. `--cut 0.10` splits harder.

### 2) build: make the character's images
```bat
animelora.bat build -p fairytail -n natsu_ft --cluster 2 --series "fairy tail"
```
- `--cluster 2 5`: if the character is split over more than one cluster, give all the numbers.
- `--ref folder`: a folder with 3 to 10 images of the character, instead of or with cluster numbers. Better for side characters.
- `-n`: the trigger word, also the name of the output folder.
- The analysis of every crop is saved in `projects\<p>\cache\`, so building again with other thresholds or options only analyses what's new. `--fresh` redoes everything.

The result in `projects\<p>\characters\<name>\`:
```
sorted\close_up\front|three_quarter|side|back|above|below\   ← a PNG image + a .txt file with its caption
sorted\upper_body\...   sorted\cowboy_shot\...   sorted\full_body\...
sorted\_review\...      ← doubtful cases: check them first
report.txt              ← statistics and the angle distribution
```

### 3) review
Open the `sorted` folder and delete every image that isn't the character, starting with the `_review` folder. You can edit the `.txt` files by hand too.

**Rejections:**
- **🚫 Not this character (N):** an image of another character. The remaining images that look like it are marked 🚫, and every later build leaves them out.
- **🗑 Bad image (Delete):** a bad image of the character itself. It's only removed.
- An image is left out when it's closer to a rejected image than to the character's own references.
- `animelora.bat reject -p fairytail -n natsu_ft v01_00616.0s_full.png` rejects an image and lists the ones that look like it. Without image names it only lists them; `--clear` forgets all rejections.

**Editing tags in bulk:**
```bat
animelora.bat tags -p fairytail -n natsu_ft
animelora.bat tags -p fairytail -n natsu_ft --remove parody --replace "yellow eyes=brown eyes"
animelora.bat tags -p fairytail -n natsu_ft --undo
```
The first lists all tags and their counts, the second removes and replaces in every caption, the third undoes the last change.

**Outfits:** when the character appears in more than one outfit, build adds a tag per outfit after the trigger word, such as `natsu_ft_outfit1`.
- Rename one with a replace, such as `natsu_ft_outfit1=natsu_ft_coat`.
- After deleting images in review: `animelora.bat outfits -p fairytail -n natsu_ft`. To skip outfit separation: `--no-outfits`.

### 4) export: prepare the training folder
```bat
animelora.bat export -p fairytail -n natsu_ft --total 100
```
Copies the images with their caption files into one folder, `train\`. Point AI Toolkit's dataset at that folder, with caption extension `txt`.
- `--total 100`: balances the angles. The count is spread over the angle folders by the square root of each folder's size, and inside each folder the picks are varied but typical.
- `--max-per-group 15`: a cap per angle folder.

**Straight into AI Toolkit, with a config file:**
```bat
animelora.bat export -p fairytail -n natsu_ft --total 60 --aitk "E:\AI-Toolkit-Easy-Install\AI-Toolkit" --dataset-name natsu_dragneel
```
- **Images:** copied to `AI-Toolkit\datasets\natsu_dragneel\`. The path is remembered, so later `--aitk` alone is enough.
- **Config file:** made from `animelora\aitk_template.yaml`, saved in the character folder and in `AI-Toolkit\config\`. In AI Toolkit create a new Job and paste its content in Advanced mode.
- **Schedule:**
  - `Save Every = Sample Every = round(images × resolutions × 10 ÷ 4)`
  - `Steps = Save Every × (epochs ÷ 10)`
  - `Max Saves = epochs ÷ 10`
  - Batch 1, Gradient Accumulation 4, Warmup 100.
- **Options:** `--epochs 50` or `60` instead of 40, and `--res 512 1024` for the resolutions.
- The Job name gets the next free version (`Natsu_Dragneel_v1`, then `v2`...), and the sample prompts use `1girl` or `1boy` depending on the character, plus one prompt per outfit.
- A folder in `datasets` with the same name that the program didn't make is never overwritten.
- To change the fixed settings (network, LR, EMA, negative prompts...): edit `animelora\aitk_template.yaml`.

### 5) clean: save disk space
```bat
animelora.bat clean -p fairytail
animelora.bat clean -p fairytail --all
```
- **Without `--all`:** deletes the frames the program will never read again (inside the OP/ED or without characters), the thumbnails, and unused images in `cache`. Building and clustering keep working.
- **With `--all`:** deletes every frame and the saved analysis. The finished images stay, but the project can't be built or clustered any more.

## What build does
| Stage | How |
|---|---|
| Recognising the character | CCIP: compares every detected character with the references; the default threshold is 0.13 |
| Cropping | Three crops: the whole body, the upper body and the head. Every head or upper-body crop is checked for identity again |
| Leaving out | Text on screen (OCR), dark or faded frames, another character overlapping, chibi and blurry drawings |
| Removing duplicates | Visual similarity (WD14 embedding) ≥ 0.80; the sharpest image is kept |
| Tags | WD14 EVA02-Large in Anima's style: lowercase, spaces instead of `_` |
| Order | `anime screencap, safe, 1boy, <trigger>, <series>, <tags...>` |
| Fixed features | Hair and eye colours and the hairstyle are removed from the captions so the trigger word learns them. To keep them: `--keep-core` |
| Angle | Tags give side, back, from above, from below. Where the eyes sit inside the face separates “three-quarter” from “front” |
| Outfits | Body crops grouped by their clothing tags, with a tag per outfit when there is more than one |
| Upscaling (optional) | `--upscale`: every image smaller than 1024 pixels is enlarged with the CDC anime upscaler, at most 4× |

## Useful options
- `report.txt` shows the distribution of match scores. If you see other characters, lower `--threshold` (e.g. 0.11); if there are too few images, raise it (e.g. 0.15).
- `--sim 0.85`: keeps more similar images; 0.75 removes duplicates more strictly.
- `--min-size 512`: rejects small crops. The default is 448, the square root of the area; with `--upscale` it is 320.
- `--upscale --upscale-to 768`: use your training resolution as the target size.
- `--save-dropped`: saves the left-out images in `_dropped\<reason>\` so you can check the filters.
- `--overwrite`: builds again and **clears** the `sorted` folder and your review with it.
