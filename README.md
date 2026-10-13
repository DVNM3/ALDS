# animelora

Turns anime episodes into a ready-to-train image set for a LoRA of one character (set up for Anima and AI Toolkit).

## Graphical interface
Double-click **`animelora-gui.bat`**. The interface opens in your browser at `http://127.0.0.1:7860`. To stop it, close the black command window.

**Language:** the interface comes in Arabic (right to left, `http://127.0.0.1:7860/`) and English (`http://127.0.0.1:7860/en`). Switch with the **Arabic | English** links at the top of the page; the language you used last opens on the next start.

| Tab | What you do there |
|---|---|
| 1. Scan episodes | Paste episode paths (or a whole folder), then press “Start scanning”. The OP/ED is found automatically and its times show in the episodes table. “💾 Disk space” shows the project's size and cleans it up |
| 2. Pick the character | Click a character's card to select it (you can select more than one) or upload reference images, type the trigger word, then “Build the image set”. If two characters got mixed in one card, select it and press “✂ Split” |
| 3. Review | Opens by itself after a build. Images marked ⚠ come first. **N** for an image of another character (the program learns from it), **Delete** for a bad image of the character itself, **← →** to move, **Ctrl+Z** to undo. You can also edit a caption, move an image that was put in the wrong group, or show one outfit only |
| 4. Tags | A table of all tags and how often they appear. Remove, replace or add a tag in **all** captions at once, with undo |
| 5. Save the result | Paste the path of the place you want; a folder named after the character is made there with the images and caption files: the dataset you train on. The last place is remembered, and saving inside the projects folder or over a folder the program didn't make is refused. Before saving you see a summary: image count, outfits, angle distribution, and a warning if images are still waiting for review. After saving you can delete the whole project from the program folder to free space, once you tick the confirmation. (Balancing and the AI Toolkit config are still in the command-line `export`) |

- **Stop button:** shows under the button of every long action while it runs: scanning, finding the OP/ED again, clustering and splitting, building, saving.
  - After you press it the action stops within seconds, everything it generated is removed, and the project is exactly as it was before.
  - A stopped scan of a new project: the whole project is removed.
  - A stopped rebuild of a character: the old images and your review come back as they were.
  - A stopped save or export: the earlier dataset folder comes back.
  - The same happens when an action fails with an error. On the command line **Ctrl+C** works the same way.
- Deleting doesn't erase images for good: they move to a `_deleted` folder inside the character folder.
- The interface only runs on your computer (127.0.0.1); nobody on the network can reach it.

## Command line

```
scan  →  pick the character's number from the image  →  build  →  review the images  →  export
```

### 1) scan: extract frames, find the characters, cluster them
```bat
animelora.bat scan -p fairytail "D:\anime\ep01.mkv" "D:\anime\ep02.mkv"
```
- You can give it a whole folder instead of files.
- **The OP/ED is found automatically:** the program compares the episodes with each other and leaves out every part repeated for 40 seconds or more. That covers the opening and ending, the short segment after them, and a long recap at the start of an episode if there is one.
  - With a single episode it uses the next episode in the same folder as the reference for the comparison, without extracting anything from it.
  - To turn it off: `--no-auto-skip`. To change the shortest length: `--auto-min 60`.
- `--skip 0:00-1:30`: more times to ignore by hand, optional.
- Running `scan` again on the same project adds new episodes, and finds the OP/ED and clusters again over all of them.
- `animelora.bat autoskip -p fairytail`: finds the OP/ED again for the scanned episodes. With `--off` nothing is left out and every frame is used.
- The result: `projects\<p>\clusters\overview.jpg`, with a row per character and its number (#1, #2 ...).
- **Cluster numbers change after every scan**, so look at the image again each time.
- `animelora.bat split -p fairytail --cluster 3`: splits a cluster where similar characters got mixed. The other clusters keep their numbers; the new parts get numbers at the end of the list. `--cut 0.10` splits harder.

### 2) build: make the character's images
```bat
animelora.bat build -p fairytail -n natsu_ft --cluster 2 --series "fairy tail"
```
- `--cluster 2 5`: if the character got split into more than one cluster (another outfit, say), give all the numbers.
- `--ref folder`: instead of a cluster number, put 3 to 10 images of the character in a folder. Better for side characters.
- `-n`: the trigger word, also the name of the output folder.
- **Rebuilding is fast:** the program saves the analysis of every crop in `projects\<p>\cache\`: crop positions, match scores, tags, text reading, face detection, and the images themselves (as cut and upscaled). When you change the match or duplicate threshold, the smallest size or the options and build again, only what's new gets analysed. The log shows how many frames came from the saved analysis.
  - The cache is shared by the characters of a project and stays valid after adding episodes. A build stopped halfway keeps what it analysed.
  - The saved images are hard-linked to the ones in `sorted`, so they take no extra space.
  - Another tagging model (`--tagger`) only redoes the tags; another upscale size only redoes the upscaling.
  - To redo everything from scratch: `--fresh`; in the interface, “Analyse from scratch” under “Advanced settings”.

The result in `projects\<p>\characters\<name>\`:
```
sorted\close_up\front|three_quarter|side|back|above|below\   ← a PNG image + a .txt file with its caption
sorted\upper_body\...   sorted\cowboy_shot\...   sorted\full_body\...
sorted\_review\...      ← doubtful cases: check them first
report.txt              ← statistics and the angle distribution
```

### 3) review
Open the `sorted` folder and delete every image that isn't the character, starting with the `_review` folder. You can edit the `.txt` files by hand too.

**Learning from rejections:** review has two ways to remove an image:
- **🚫 Not this character (N):** an image of another character. The program learns from it: it marks the remaining images that look like it with 🚫 (all of them under “🚫 Like what you rejected” in the “Show” list) and leaves out what looks like it in every later build.
- **🗑 Bad image (Delete):** an image of the character itself that is just bad. It's only removed and nothing is learned from it; otherwise correct images of the character would be left out.
- **The rule:** an image is left out when it's closer to a rejected image than to the character's own references. In a test on Fairy Tail (Gray at a loose match threshold of 0.18), rejecting one image of Lyon marked 20 of his 22 other images, and no image of Gray. After rejecting two images and building again, 21 of 23 Lyon images and 2 of Natsu were left out, and no image of Gray.
- What the program learned carries over to rebuilds. Undo (Ctrl+Z) undoes the learning too, and “Forget all images rejected as another character” clears it all.
- Characters built before this feature need one rebuild for rejections to work; it takes seconds from the saved analysis.
- **On the command line:** `animelora.bat reject -p fairytail -n natsu_ft v01_00616.0s_full.png` rejects an image and lists the ones that look like it. Without image names it only lists the look-alikes; `--clear` forgets all rejections.

**Editing tags in bulk:**
```bat
animelora.bat tags -p fairytail -n natsu_ft
animelora.bat tags -p fairytail -n natsu_ft --remove parody --replace "yellow eyes=brown eyes"
animelora.bat tags -p fairytail -n natsu_ft --undo
```
The first command, without options, lists all tags and their counts. The second removes and replaces in every caption. The third undoes the last change.

**Outfits:** when the character appears in more than one outfit, build adds a tag per outfit after the trigger word, such as `natsu_ft_outfit1`. After training you call up the outfit with that tag.
- `report.txt` and the tags tab show what sets each outfit apart; rename one with a replace, such as `natsu_ft_outfit1=natsu_ft_coat`.
- After deleting images in review, separate the outfits again: `animelora.bat outfits -p fairytail -n natsu_ft`. To skip outfit separation in a build: `--no-outfits`.

### 4) export: prepare the training folder
```bat
animelora.bat export -p fairytail -n natsu_ft --total 100
```
Copies the images with their caption files into one folder, `train\`. Point AI Toolkit's dataset at that folder, with caption extension `txt`.
- `--total 100`: balances the angles. The count is spread over the angle folders by the square root of each folder's size: big folders (front views) shrink the most, rare ones (back, side) are kept fully or mostly, and front and three-quarter views stay the largest.
  - Inside each folder the picks are varied but typical: each one stands for a group of similar images, so outliers like gag faces or odd crops aren't preferred. Sharper images come first.
- `--max-per-group 15`: a cap per angle folder.

**Straight into AI Toolkit, with a config file:**
```bat
animelora.bat export -p fairytail -n natsu_ft --total 60 --aitk "E:\AI-Toolkit-Easy-Install\AI-Toolkit" --dataset-name natsu_dragneel
```
- **Images:** copied to `AI-Toolkit\datasets\natsu_dragneel\`. The path is remembered, so later `--aitk` alone is enough.
- **Config file:** a YAML file is made from your template (`animelora\aitk_template.yaml`, a copy of “Anima AI toolkit setteings.yaml”). It's saved in the character folder and in `AI-Toolkit\config\`; in AI Toolkit you create a new Job and paste its content in Advanced mode.
- **Calculator values:** computed from the number of images actually exported, with the same formula as `anima-lora-calculator.html`:
  - `Save Every = Sample Every = round(images × resolutions × 10 ÷ 4)`
  - `Steps = Save Every × (epochs ÷ 10)`
  - `Max Saves = epochs ÷ 10`
  - Fixed: Batch 1, Gradient Accumulation 4, Warmup 100.
- **Options:** `--epochs 50` or `60` instead of 40, and `--res 512 1024` for the resolutions. The log shows what the calculator warns about, such as a large warmup or a resolution outside the recipe.
- **Filled in automatically:** the trigger word (`trigger_word`), your folder paths, the Job name with the next version (`Natsu_Dragneel_v1`, then `v2`...), and sample prompts shaped like your template's: `1girl` or `1boy` depending on the character, one prompt per outfit if there are outfits, and one without the trigger word for comparison.
- **Protection:** if `datasets` already holds a folder with that name that the program didn't make (like your older datasets), the program refuses to write into it.
- **To change the fixed settings** (network, LR, EMA, negative prompts...): edit `animelora\aitk_template.yaml`.

### 5) clean: save disk space
```bat
animelora.bat clean -p fairytail
animelora.bat clean -p fairytail --all
```
- **Without `--all`:** completely safe. Deletes the frames the program will never read again (inside the OP/ED, or without characters in projects scanned before that was skipped at scan time), the thumbnails, and the images in `cache` no build uses any more. Building and clustering keep working.
  - OP/ED frames deleted this way don't come back. If you stop leaving the OP/ED out (`autoskip --off`) or the detected OP/ED changes (after scanning a new episode, say), those frames stay out of building and clustering, and the log tells how many. To get them back, scan the episodes again in a new project.
- **With `--all`:** deletes every frame and keeps the finished images, but the project can't be built or clustered any more. The saved analysis (`cache`) goes too, since it's no use after that.

## What build does by itself
| Stage | How |
|---|---|
| Recognising the character | CCIP: compares every detected character with the references; the default threshold is 0.13 |
| Cropping | Three crops: the whole body, the upper body and the head. Every head or upper-body crop is checked for identity again |
| Leaving out | Text on screen (by actually reading it with OCR), dark or faded frames, another character overlapping, chibi and blurry drawings |
| Removing duplicates | Visual similarity (WD14 embedding) ≥ 0.80; the sharpest image is kept |
| Tags | WD14 EVA02-Large in Anima's style: lowercase, spaces instead of `_` |
| Order | `anime screencap, safe, 1boy, <trigger>, <series>, <tags...>` |
| Fixed features | Hair and eye colours and the hairstyle are removed from the captions so the trigger word learns them. To keep them: `--keep-core` |
| Angle | Tags give side, back, from above, from below. Where the eyes sit inside the face separates “three-quarter” from “front” |
| Outfits | Body crops grouped by their clothing tags, with a tag per outfit when there is more than one |
| Upscaling (optional) | `--upscale`: every image smaller than 1024 pixels is enlarged with the CDC anime upscaler, at most 4×. It runs after filtering and removing duplicates, so no time goes into images that get dropped |

## Useful options
- `report.txt` shows the distribution of match scores. If you see other characters, lower `--threshold` (e.g. 0.11); if there are too few images, raise it (e.g. 0.15).
- `--sim 0.85`: keeps more similar images; 0.75 removes duplicates more strictly.
- `--min-size 512`: rejects small crops. The default is 448, the square root of the area. With `--upscale` it becomes 320, since upscaling makes small crops usable.
- `--upscale --upscale-to 768`: use your AI Toolkit training resolution as the target size.
  - Upscaling sharpens the lines but can't add details the animators didn't draw; characters far away are drawn simpler to begin with.
  - The review tab shows each image's upscale factor (e.g. “upscaled ×3.2”); check the ones with a big factor.
  - Time cost: about one extra minute per 100 images.
- `--save-dropped`: saves the left-out images in `_dropped\<reason>\` so you can check the filters.
- `--overwrite`: to build again; this **clears** the `sorted` folder and your manual review with it.

## Performance (RTX 5070 Ti)
- scan: about 3.5 minutes per 24-minute 1080p episode, down from more than 6.
  - Character detection runs while the episode is being decoded, on 3 parallel threads, so extracting and detecting together take 144 seconds instead of 293.
  - Decoding alone takes 58 seconds, the floor. The rest is finding the OP/ED and clustering.
  - When a project has a single episode, the program checks the next episode to find the OP/ED. That check now decodes only about half the frames (it skips the frames no other frame depends on): 33–44 seconds instead of 57–68 for a Fairy Tail episode, with the same OP/ED found.
  - Every thread loads its own copy of the detection models, so the graphics card uses up to about 8 GB during a scan.
- First build: 1 to 3 minutes depending on how many images the character has, more with upscaling.
  - Its longest stage is reading text on screen, especially in anime with a lot of writing; in One Room it was half the build time.
  - Text detection used to run twice on every crop with text; it now runs once. PNG files are saved with lighter compression: twice as fast, only 7% bigger, and no difference in the image.
  - The result on One Room: 162 seconds instead of 197, with identical images and captions.
- Rebuilding from the saved analysis (a test on one episode, 614 frames of the character):
  - Same settings: 6 seconds instead of 194; with upscaling 6.5 seconds instead of 270.
  - Match threshold 0.15, duplicate threshold 0.75, smallest size 384: 32 seconds instead of 202, since only 86 new frames needed analysis.
- Extracted frames take hundreds of megabytes per episode in `projects\<p>\frames` (Fairy Tail episode 16 took 916 MB before the change below); you can delete them once the project is done.
  - A scan only keeps the frames with a character big enough to recognise, since the program never opens the others. Example: three One Room episodes kept 715 frames (275 MB) instead of 938 (342 MB).
  - OP/ED frames are kept, because the OP/ED is found after the scan and `autoskip --off` can bring them back. A safe clean deletes them.

## Installing on a new computer
```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
The models download from HuggingFace by themselves on the first run.
