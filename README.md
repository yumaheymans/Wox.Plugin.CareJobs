# CareJobs.Now for Wox

A single-file [Wox](https://github.com/Wox-launcher/Wox) plugin (Python) that searches open US healthcare jobs on [CareJobs.Now](https://carejobs.now), with the pay each employer posts.

Type `cj`, a space and what you are looking for:

- `cj icu nurse tx`
- `cj travel cna phoenix`
- `cj medical assistant ohio`
- `cj remote coding`

A trailing state (its two-letter code or its name) narrows the search to that state, and `remote` finds work-from-home jobs. Each result shows the job, its employer, the posted pay, the place and the date it was listed. Enter opens the job; the action panel also opens the employer's page. The last row opens every matching job on the site.

## Install

From the Wox plugin store (search CareJobs.Now), or put [Wox.Plugin.CareJobs.py](Wox.Plugin.CareJobs.py) in Wox's single-file plugin folder (`~/.wox/wox-user/plugins/single-file/`). Windows, macOS and Linux.

## Privacy

Only what you type after `cj` is sent, to `https://carejobs.now/api/mcp` (CareJobs.Now's free public API). No account, no key, no tracking. [Privacy policy](https://carejobs.now/legal/privacy).

License: MIT. More ways to use CareJobs.Now: https://carejobs.now/apps
