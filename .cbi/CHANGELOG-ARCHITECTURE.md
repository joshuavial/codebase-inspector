# Architecture changelog

## 2026-10-10 841b92359571 by joshuavial

### structural diff

#### deeplinks  Deep links

- relationship-volume  Deep links -> Desktop shell  resolves the project, worktree and comparison the link names  calls 6 -> 7  imports 3 -> 4
  - app/src/deeplink.ts  deeplink.ts
  - app/src/deeplink.ts  openComparison
  - app/src/deeplink.ts  realGh
  - app/src/deeplink.ts  validateOpen
- symbol-changed  body  app/src/deeplink.ts#toplevel
  - app/src/deeplink.ts  toplevel
- symbol-changed  body  app/src/deeplink.ts#validateOpen
  - app/src/deeplink.ts  validateOpen

#### shell  Desktop shell

- symbol-changed  body  app/src/compare.ts#resolveSide
  - app/src/compare.ts  resolveSide
- symbol-changed  body  app/src/editor.ts#macCandidates
  - app/src/editor.ts  macCandidates
- symbol-changed  body  app/src/fast-open.ts#instantOpen
  - app/src/fast-open.ts  instantOpen
- symbol-changed  body  app/src/switcher.ts#samePath
  - app/src/switcher.ts  samePath
- symbol-changed  body  app/src/switcher.ts#worktreeForFolder
  - app/src/switcher.ts  worktreeForFolder
- symbol-changed  signature  app/src/project.ts#resolveProject
  - app/src/project.ts  resolveProject

## 2026-10-09 a735ab902a66 by joshuavial

### structural diff

#### parse  Parsing and resolution

- symbol-added  tests/drawer_open_check.js#makeEl
  - tests/drawer_open_check.js  makeEl

#### viewer  Static viewer

- symbol-added  src/cbi/viewer/app.js#drawerOpen
  - src/cbi/viewer/app.js  drawerOpen
- symbol-added  src/cbi/viewer/app.js#drawerSectionName
  - src/cbi/viewer/app.js  drawerSectionName
- symbol-added  src/cbi/viewer/app.js#readDrawerOpen
  - src/cbi/viewer/app.js  readDrawerOpen
- symbol-changed  body  src/cbi/viewer/app.js#drawer
  - src/cbi/viewer/app.js  drawer
- symbol-changed  body  src/cbi/viewer/app.js#envList
  - src/cbi/viewer/app.js  envList
- symbol-changed  body  src/cbi/viewer/app.js#fold
  - src/cbi/viewer/app.js  fold
- symbol-changed  body  src/cbi/viewer/app.js#integrationList
  - src/cbi/viewer/app.js  integrationList
- test-added  tests/test_layout.py#test_drawer_keeps_restored_sections_on_the_same_view
  - tests/test_layout.py  test_drawer_keeps_restored_sections_on_the_same_view

## 2026-10-09 5eebc0fa7e75 by joshuavial

### structural diff

#### queries  Queries

- symbol-changed  body  src/cbi/ingest.py#Model
  - src/cbi/ingest.py  Model
- symbol-changed  body  src/cbi/ingest.py#Model.file
  - src/cbi/ingest.py  file
- test-added  tests/test_ingest.py#test_a_path_on_another_drive_is_unmapped
  - tests/test_ingest.py  test_a_path_on_another_drive_is_unmapped

## 2026-10-09 d1825ba9f4f2 by joshuavial

### structural diff

#### shell  Desktop shell

- symbol-added  tests/test_install_app.py#_bash_script
  - tests/test_install_app.py  _bash_script
- symbol-changed  body  tests/test_install_app.py#_bash
  - tests/test_install_app.py  _bash
- untested  tests/test_install_app.py#_bash
  - tests/test_install_app.py  _bash

#### scan  Scanning and enumeration

- symbol-added  tests/conftest.py#_git_argv
  - tests/conftest.py  _git_argv
- symbol-added  tests/conftest.py#_interpreter
  - tests/conftest.py  _interpreter
- symbol-added  tests/conftest.py#_write_text_lf
  - tests/conftest.py  _write_text_lf
- symbol-changed  body  tests/conftest.py#_rewrite_argv
  - tests/conftest.py  _rewrite_argv
- symbol-changed  body  tests/conftest.py#subprocess_defaults
  - tests/conftest.py  subprocess_defaults

#### review  Review

- symbol-changed  body  src/cbi/review.py#open_link
  - src/cbi/review.py  open_link

## 2026-10-09 a957011b358c by joshuavial

### structural diff

#### shell  Desktop shell

- symbol-added  tests/test_install_app.py#_bash
  - tests/test_install_app.py  _bash

#### render  Rendering

- symbol-added  tests/test_render.py#_pid_dead
  - tests/test_render.py  _pid_dead

#### scan  Scanning and enumeration

- symbol-added  tests/conftest.py#_popen_rewritten
  - tests/conftest.py  _popen_rewritten
- symbol-added  tests/conftest.py#_python_standin
  - tests/conftest.py  _python_standin
- symbol-added  tests/conftest.py#_rewrite_argv
  - tests/conftest.py  _rewrite_argv
- symbol-added  tests/conftest.py#_run_with_timeout
  - tests/conftest.py  _run_with_timeout
- symbol-added  tests/conftest.py#subprocess_defaults
  - tests/conftest.py  subprocess_defaults
- symbol-added  tests/conftest.py#write_standin
  - tests/conftest.py  write_standin
- symbol-changed  body  tests/conftest.py#make_repo
  - tests/conftest.py  make_repo
- symbol-changed  body  tests/test_refs.py#_git_shim
  - tests/test_refs.py  _git_shim
- untested  tests/test_refs.py#_git_shim
  - tests/test_refs.py  _git_shim

#### deeplinks  Deep links

- symbol-changed  signature+body  tests/test_open.py#_fake_gh
  - tests/test_open.py  _fake_gh
- untested  tests/test_open.py#_fake_gh
  - tests/test_open.py  _fake_gh

#### review  Review

- symbol-changed  body  tests/test_change_review.py#fake_gh
  - tests/test_change_review.py  fake_gh
- untested  tests/test_change_review.py#fake_gh
  - tests/test_change_review.py  fake_gh

## 2026-10-09 ae7498f032f2 by joshuavial

### structural diff

#### cli  Command line

- symbol-added  src/cbi/cli.py#_is_broken_pipe
  - src/cbi/cli.py  _is_broken_pipe
- symbol-changed  body  src/cbi/cli.py#main
  - src/cbi/cli.py  main
- symbol-changed  body  src/cbi/editor.py#_join_program
  - src/cbi/editor.py  _join_program

#### queries  Queries

- symbol-changed  body  src/cbi/ingest.py#Model
  - src/cbi/ingest.py  Model
- symbol-changed  body  src/cbi/ingest.py#Model.file
  - src/cbi/ingest.py  file

## 2026-10-09 494bacde209d by joshuavial

### structural diff

#### updates  Release check

- concept-added  Release check
  - app/src/update-check.test.ts  update-check.test.ts
  - app/src/update-check.ts  update-check.ts
  - app/test/update-smoke.mjs  update-smoke.mjs
  - src/cbi/update_check.py  update_check.py
  - tests/test_update_check.py  test_update_check.py
- integration-added  Release check -> GitHub releases  GETs the latest release for the CLI notice  HTTP
- integration-added  Release check -> GitHub releases  GETs the latest release for the desktop banner  HTTP
- env-read  CBI_NO_UPDATE_CHECK
  - app/src/main.ts  checkForUpdatesOnce
  - app/src/main.ts  registerIpc
  - app/src/main.ts  startAutomaticUpdateChecks
  - src/cbi/update_check.py  _disabled
- env-read  LOCALAPPDATA
  - src/cbi/update_check.py  platform_cache_dir
- env-read  XDG_CACHE_HOME
  - src/cbi/update_check.py  platform_cache_dir
- symbol-added  app/src/update-check.test.ts#apiRelease
  - app/src/update-check.test.ts  apiRelease
- symbol-added  app/src/update-check.test.ts#check
  - app/src/update-check.test.ts  check
- symbol-added  app/src/update-check.test.ts#listen
  - app/src/update-check.test.ts  listen
- symbol-added  app/src/update-check.test.ts#respond
  - app/src/update-check.test.ts  respond
- symbol-added  app/src/update-check.ts#CheckResult
  - app/src/update-check.ts  CheckResult
- symbol-added  app/src/update-check.ts#FetchResponse
  - app/src/update-check.ts  FetchResponse
- symbol-added  app/src/update-check.ts#UpdateAsset
  - app/src/update-check.ts  UpdateAsset
- symbol-added  app/src/update-check.ts#UpdateBanner
  - app/src/update-check.ts  UpdateBanner
- symbol-added  app/src/update-check.ts#UpdateRelease
  - app/src/update-check.ts  UpdateRelease
- symbol-added  app/src/update-check.ts#UpdateState
  - app/src/update-check.ts  UpdateState
- symbol-added  app/src/update-check.ts#archOf
  - app/src/update-check.ts  archOf
- symbol-added  app/src/update-check.ts#bannerFor
  - app/src/update-check.ts  bannerFor
- symbol-added  app/src/update-check.ts#cloneState
  - app/src/update-check.ts  cloneState
- symbol-added  app/src/update-check.ts#downloadUrl
  - app/src/update-check.ts  downloadUrl
- symbol-added  app/src/update-check.ts#emptyState
  - app/src/update-check.ts  emptyState
- symbol-added  app/src/update-check.ts#fetchRelease
  - app/src/update-check.ts  fetchRelease
- symbol-added  app/src/update-check.ts#hasWord
  - app/src/update-check.ts  hasWord
- symbol-added  app/src/update-check.ts#headerValue
  - app/src/update-check.ts  headerValue
- symbol-added  app/src/update-check.ts#isNewer
  - app/src/update-check.ts  isNewer
- symbol-added  app/src/update-check.ts#platformOf
  - app/src/update-check.ts  platformOf
- symbol-added  app/src/update-check.ts#readState
  - app/src/update-check.ts  readState
- symbol-added  app/src/update-check.ts#releaseFromApi
  - app/src/update-check.ts  releaseFromApi
- symbol-added  app/src/update-check.ts#requestOnce
  - app/src/update-check.ts  requestOnce
- symbol-added  app/src/update-check.ts#runCheck
  - app/src/update-check.ts  runCheck
- symbol-added  app/src/update-check.ts#semver
  - app/src/update-check.ts  semver
- symbol-added  app/src/update-check.ts#setAutoCheck
  - app/src/update-check.ts  setAutoCheck
- symbol-added  app/src/update-check.ts#skipRelease
  - app/src/update-check.ts  skipRelease
- symbol-added  app/src/update-check.ts#storedRelease
  - app/src/update-check.ts  storedRelease
- symbol-added  app/src/update-check.ts#versionOf
  - app/src/update-check.ts  versionOf
- symbol-added  app/src/update-check.ts#writeState
  - app/src/update-check.ts  writeState
- symbol-added  app/test/update-smoke.mjs#fail
  - app/test/update-smoke.mjs  fail
- symbol-added  app/test/update-smoke.mjs#git
  - app/test/update-smoke.mjs  git
- symbol-added  app/test/update-smoke.mjs#shellQuote
  - app/test/update-smoke.mjs  shellQuote
- symbol-added  src/cbi/update_check.py#_call
  - src/cbi/update_check.py  _call
- symbol-added  src/cbi/update_check.py#_disabled
  - src/cbi/update_check.py  _disabled
- symbol-added  src/cbi/update_check.py#_is_newer
  - src/cbi/update_check.py  _is_newer
- symbol-added  src/cbi/update_check.py#_line
  - src/cbi/update_check.py  _line
- symbol-added  src/cbi/update_check.py#_notice
  - src/cbi/update_check.py  _notice
- symbol-added  src/cbi/update_check.py#_parse
  - src/cbi/update_check.py  _parse
- symbol-added  src/cbi/update_check.py#_parts
  - src/cbi/update_check.py  _parts
- symbol-added  src/cbi/update_check.py#_read_cache
  - src/cbi/update_check.py  _read_cache
- symbol-added  src/cbi/update_check.py#_remember
  - src/cbi/update_check.py  _remember
- symbol-added  src/cbi/update_check.py#_valid_latest
  - src/cbi/update_check.py  _valid_latest
- symbol-added  src/cbi/update_check.py#_version_text
  - src/cbi/update_check.py  _version_text
- symbol-added  src/cbi/update_check.py#_write_cache
  - src/cbi/update_check.py  _write_cache
- symbol-added  src/cbi/update_check.py#cache_dir
  - src/cbi/update_check.py  cache_dir
- symbol-added  src/cbi/update_check.py#cache_file
  - src/cbi/update_check.py  cache_file
- symbol-added  src/cbi/update_check.py#current_version
  - src/cbi/update_check.py  current_version
- symbol-added  src/cbi/update_check.py#fetch_release
  - src/cbi/update_check.py  fetch_release
- symbol-added  src/cbi/update_check.py#notice
  - src/cbi/update_check.py  notice
- symbol-added  src/cbi/update_check.py#platform_cache_dir
  - src/cbi/update_check.py  platform_cache_dir
- symbol-added  tests/test_update_check.py#_body
  - tests/test_update_check.py  _body
- symbol-added  tests/test_update_check.py#_enable
  - tests/test_update_check.py  _enable
- symbol-added  tests/test_update_check.py#_fetch
  - tests/test_update_check.py  _fetch
- test-added  app/src/update-check.test.ts#a 304 keeps the cached release
  - app/src/update-check.test.ts  a 304 keeps the cached release
- test-added  app/src/update-check.test.ts#a newer release becomes a banner and prefers the asset for this machine
  - app/src/update-check.test.ts  a newer release becomes a banner and prefers the asset for this machine
- test-added  app/src/update-check.test.ts#a prerelease or a draft is ignored
  - app/src/update-check.test.ts  a prerelease or a draft is ignored
- test-added  app/src/update-check.test.ts#an API error fails silently unless the check was asked for
  - app/src/update-check.test.ts  an API error fails silently unless the check was asked for
- test-added  app/src/update-check.test.ts#an asset is chosen for the OS and arch, otherwise the release page
  - app/src/update-check.test.ts  an asset is chosen for the OS and arch, otherwise the release page
- test-added  app/src/update-check.test.ts#an automatic banner shows at most once a day
  - app/src/update-check.test.ts  an automatic banner shows at most once a day
- test-added  app/src/update-check.test.ts#automatic checks stay off when the setting is off, and a manual check still runs
  - app/src/update-check.test.ts  automatic checks stay off when the setting is off, and a manual check still runs
- test-added  app/src/update-check.test.ts#fetch follows a redirect and honours an etag
  - app/src/update-check.test.ts  fetch follows a redirect and honours an etag
- test-added  app/src/update-check.test.ts#fetch gives up when the server does not answer
  - app/src/update-check.test.ts  fetch gives up when the server does not answer
- test-added  app/src/update-check.test.ts#offline fails silently unless the check was asked for
  - app/src/update-check.test.ts  offline fails silently unless the check was asked for
- test-added  app/src/update-check.test.ts#skip remembers that version and a later one still shows
  - app/src/update-check.test.ts  skip remembers that version and a later one still shows
- test-added  app/src/update-check.test.ts#the same version and an older version are not updates
  - app/src/update-check.test.ts  the same version and an older version are not updates
- test-added  app/src/update-check.test.ts#the saved check defaults to on and a damaged file is ignored
  - app/src/update-check.test.ts  the saved check defaults to on and a damaged file is ignored
- test-added  tests/test_update_check.py#test_a_failed_refresh_still_prints_the_cached_release
  - tests/test_update_check.py  test_a_failed_refresh_still_prints_the_cached_release
- test-added  tests/test_update_check.py#test_a_hung_fetch_does_not_block_past_the_timeout
  - tests/test_update_check.py  test_a_hung_fetch_does_not_block_past_the_timeout
- test-added  tests/test_update_check.py#test_cache_file_follows_cbi_cache_dir_or_the_platform_dir
  - tests/test_update_check.py  test_cache_file_follows_cbi_cache_dir_or_the_platform_dir
- test-added  tests/test_update_check.py#test_ci_and_the_env_opt_out_skip_the_check
  - tests/test_update_check.py  test_ci_and_the_env_opt_out_skip_the_check
- test-added  tests/test_update_check.py#test_etag_304_reuses_the_cached_release
  - tests/test_update_check.py  test_etag_304_reuses_the_cached_release
- test-added  tests/test_update_check.py#test_fetch_release_sends_a_user_agent_and_honours_etag
  - tests/test_update_check.py  test_fetch_release_sends_a_user_agent_and_honours_etag
- test-added  tests/test_update_check.py#test_newer_release_is_cached_for_a_day
  - tests/test_update_check.py  test_newer_release_is_cached_for_a_day
- test-added  tests/test_update_check.py#test_numeric_semver_orders_double_digits
  - tests/test_update_check.py  test_numeric_semver_orders_double_digits
- test-added  tests/test_update_check.py#test_offline_is_cached_and_does_not_raise
  - tests/test_update_check.py  test_offline_is_cached_and_does_not_raise
- test-added  tests/test_update_check.py#test_prerelease_and_draft_are_ignored
  - tests/test_update_check.py  test_prerelease_and_draft_are_ignored
- test-added  tests/test_update_check.py#test_prime_and_status_print_the_notice
  - tests/test_update_check.py  test_prime_and_status_print_the_notice
- test-added  tests/test_update_check.py#test_same_and_older_releases_say_nothing
  - tests/test_update_check.py  test_same_and_older_releases_say_nothing
- test-added  tests/test_update_check.py#test_version_flag_prints_the_version
  - tests/test_update_check.py  test_version_flag_prints_the_version

#### cli  Command line

- relationship-added  Command line -> Release check  prints the cached newer-release notice on prime and status  calls 1  imports 1
  - src/cbi/cli.py  _print_update_notice
  - src/cbi/cli.py  cli.py
- symbol-added  src/cbi/cli.py#_print_update_notice
  - src/cbi/cli.py  _print_update_notice
- symbol-changed  body  src/cbi/cli.py#_main
  - src/cbi/cli.py  _main
- symbol-changed  body  src/cbi/cli.py#cmd_status
  - src/cbi/cli.py  cmd_status

#### shell  Desktop shell

- relationship-added  Desktop shell -> Release check  runs the release check and shows or skips the banner  calls 11  imports 1
  - app/src/main.ts  checkForUpdatesOnce
  - app/src/main.ts  main.ts
  - app/src/main.ts  registerIpc
- env-read  CBI_NO_UPDATE_CHECK
  - app/src/main.ts  checkForUpdatesOnce
  - app/src/main.ts  registerIpc
  - app/src/main.ts  startAutomaticUpdateChecks
  - src/cbi/update_check.py  _disabled
- env-read  CBI_UPDATE_URL
  - app/src/main.ts  releasesUrl
- symbol-added  app/src/main.ts#checkForUpdates
  - app/src/main.ts  checkForUpdates
- symbol-added  app/src/main.ts#checkForUpdatesItem
  - app/src/main.ts  checkForUpdatesItem
- symbol-added  app/src/main.ts#checkForUpdatesOnce
  - app/src/main.ts  checkForUpdatesOnce
- symbol-added  app/src/main.ts#enqueueUpdate
  - app/src/main.ts  enqueueUpdate
- symbol-added  app/src/main.ts#openExternalUrl
  - app/src/main.ts  openExternalUrl
- symbol-added  app/src/main.ts#releasesUrl
  - app/src/main.ts  releasesUrl
- symbol-added  app/src/main.ts#showUpdateNotice
  - app/src/main.ts  showUpdateNotice
- symbol-added  app/src/main.ts#startAutomaticUpdateChecks
  - app/src/main.ts  startAutomaticUpdateChecks
- symbol-added  app/src/main.ts#updateStatePath
  - app/src/main.ts  updateStatePath
- symbol-added  app/src/renderer.ts#CbiApi.dismissUpdate
  - app/src/renderer.ts  dismissUpdate
- symbol-added  app/src/renderer.ts#CbiApi.getUpdateSetting
  - app/src/renderer.ts  getUpdateSetting
- symbol-added  app/src/renderer.ts#CbiApi.onUpdateBanner
  - app/src/renderer.ts  onUpdateBanner
- symbol-added  app/src/renderer.ts#CbiApi.openUpdate
  - app/src/renderer.ts  openUpdate
- symbol-added  app/src/renderer.ts#CbiApi.setUpdateSetting
  - app/src/renderer.ts  setUpdateSetting
- symbol-added  app/src/renderer.ts#CbiApi.skipUpdate
  - app/src/renderer.ts  skipUpdate
- symbol-added  app/src/renderer.ts#renderUpdate
  - app/src/renderer.ts  renderUpdate
- symbol-changed  body  app/src/main.ts#applyBounds
  - app/src/main.ts  applyBounds
- symbol-changed  body  app/src/main.ts#installEditMenu
  - app/src/main.ts  installEditMenu
- symbol-changed  body  app/src/main.ts#registerIpc
  - app/src/main.ts  registerIpc
- symbol-changed  body  app/src/main.ts#rescan
  - app/src/main.ts  rescan
- symbol-changed  body  app/src/renderer.ts#CbiApi
  - app/src/renderer.ts  CbiApi
- symbol-changed  body  app/src/view-state.ts#writeFile
  - app/src/view-state.ts  writeFile
- untested  app/src/main.ts#applyBounds
  - app/src/main.ts  applyBounds
- untested  app/src/main.ts#installEditMenu
  - app/src/main.ts  installEditMenu
- untested  app/src/main.ts#registerIpc
  - app/src/main.ts  registerIpc
- untested  app/src/main.ts#rescan
  - app/src/main.ts  rescan
- untested  app/src/renderer.ts#CbiApi
  - app/src/renderer.ts  CbiApi

#### scan  Scanning and enumeration

- symbol-changed  body  tests/conftest.py#answer_cache
  - tests/conftest.py  answer_cache
- untested  tests/conftest.py#answer_cache
  - tests/conftest.py  answer_cache

## 2026-10-09 ab51c3e476f8 by joshuavial

### structural diff

#### tasks  Judgement tasks

- symbol-changed  body  src/cbi/prime.py#pending_guide
  - src/cbi/prime.py  pending_guide

## 2026-10-09 2545f748d27b by joshuavial

### structural diff

#### viewer  Static viewer

- symbol-removed  src/cbi/viewer/app.js#assignLanes
  - src/cbi/viewer/app.js  assignLanes
- symbol-changed  body  src/cbi/viewer/app.js#lanePlan
  - src/cbi/viewer/app.js  lanePlan
- symbol-changed  body  tests/layout_check.js#main
  - tests/layout_check.js  main
- untested  tests/layout_check.js#main
  - tests/layout_check.js  main

## 2026-10-09 7783b219c3dd by joshuavial

### structural diff

#### viewer  Static viewer

- symbol-added  src/cbi/viewer/app.js#assignLanes
  - src/cbi/viewer/app.js  assignLanes
- symbol-added  src/cbi/viewer/app.js#edgeLabelBox
  - src/cbi/viewer/app.js  edgeLabelBox
- symbol-added  src/cbi/viewer/app.js#exitX
  - src/cbi/viewer/app.js  exitX
- symbol-added  src/cbi/viewer/app.js#labelStackH
  - src/cbi/viewer/app.js  labelStackH
- symbol-added  src/cbi/viewer/app.js#lanePlan
  - src/cbi/viewer/app.js  lanePlan
- symbol-added  src/cbi/viewer/app.js#outsideEnd
  - src/cbi/viewer/app.js  outsideEnd
- symbol-added  src/cbi/viewer/app.js#placeAround
  - src/cbi/viewer/app.js  placeAround
- symbol-added  src/cbi/viewer/app.js#sideGutter
  - src/cbi/viewer/app.js  sideGutter
- symbol-added  src/cbi/viewer/app.js#spreadCenters
  - src/cbi/viewer/app.js  spreadCenters
- symbol-added  src/cbi/viewer/app.js#stampRoutes
  - src/cbi/viewer/app.js  stampRoutes
- symbol-added  src/cbi/viewer/app.js#verticalItems
  - src/cbi/viewer/app.js  verticalItems
- symbol-changed  body  src/cbi/viewer/app.js#layoutBridged
  - src/cbi/viewer/app.js  layoutBridged
- symbol-changed  body  tests/layout_check.js#main
  - tests/layout_check.js  main
- untested  tests/layout_check.js#main
  - tests/layout_check.js  main

## 2026-10-09 5f04f4bfe765 by joshuavial

### structural diff

#### shell  Desktop shell

- env-read  CI
  - app/test/editor-ref.mjs  editor-ref.mjs
  - app/test/smoke.mjs  smoke.mjs

## 2026-10-09 dee8f6d4811d by joshuavial

### structural diff

#### shell  Desktop shell

- env-unread  CBI_ALLOW_VISIBLE_SMOKE
  - app/test/smoke.mjs  smoke.mjs
- symbol-added  app/src/main.ts#yieldFocus
  - app/src/main.ts  yieldFocus
- symbol-changed  body  app/src/main.ts#createWindow
  - app/src/main.ts  createWindow
- untested  app/src/main.ts#createWindow
  - app/src/main.ts  createWindow

## 2026-10-09 7f5ac5261a4a by joshuavial

### structural diff

#### shell  Desktop shell

- relationship-volume  Desktop shell -> Deep links  handles a cbi://open URL in the running app  calls 7 -> 8  imports 1 -> 1
  - app/src/main.ts  flushLinks
  - app/src/main.ts  handleDeepLink
  - app/src/main.ts  loadComparison
  - app/src/main.ts  main.ts
  - app/src/main.ts  startCompare
- env-read  CBI_HEADLESS
  - app/src/main.ts  main.ts
- symbol-added  app/src/main.ts#revealLink
  - app/src/main.ts  revealLink
- symbol-added  app/src/reveal.test.ts#fake
  - app/src/reveal.test.ts  fake
- symbol-added  app/src/reveal.ts#RevealTarget
  - app/src/reveal.ts  RevealTarget
- symbol-added  app/src/reveal.ts#RevealTarget.focus
  - app/src/reveal.ts  focus
- symbol-added  app/src/reveal.ts#RevealTarget.isDestroyed
  - app/src/reveal.ts  isDestroyed
- symbol-added  app/src/reveal.ts#RevealTarget.isMinimized
  - app/src/reveal.ts  isMinimized
- symbol-added  app/src/reveal.ts#RevealTarget.restore
  - app/src/reveal.ts  restore
- symbol-added  app/src/reveal.ts#RevealTarget.show
  - app/src/reveal.ts  show
- symbol-added  app/src/reveal.ts#RevealTarget.showInactive
  - app/src/reveal.ts  showInactive
- symbol-added  app/src/reveal.ts#revealFor
  - app/src/reveal.ts  revealFor
- symbol-added  app/src/reveal.ts#revealWindow
  - app/src/reveal.ts  revealWindow
- symbol-changed  body  app/src/main.ts#focusWindow
  - app/src/main.ts  focusWindow
- symbol-changed  body  app/src/main.ts#handleDeepLink
  - app/src/main.ts  handleDeepLink
- symbol-changed  body  app/src/main.ts#openCompareLink
  - app/src/main.ts  openCompareLink
- symbol-changed  body  app/src/main.ts#refuse
  - app/src/main.ts  refuse
- symbol-changed  signature+body  app/src/main.ts#createWindow
  - app/src/main.ts  createWindow
- untested  app/src/main.ts#createWindow
  - app/src/main.ts  createWindow
- untested  app/src/main.ts#focusWindow
  - app/src/main.ts  focusWindow
- untested  app/src/main.ts#handleDeepLink
  - app/src/main.ts  handleDeepLink
- untested  app/src/main.ts#openCompareLink
  - app/src/main.ts  openCompareLink
- untested  app/src/main.ts#refuse
  - app/src/main.ts  refuse
- test-added  app/src/reveal.test.ts#a CLI or deep link shows the window inactive and does not focus it
  - app/src/reveal.test.ts  a CLI or deep link shows the window inactive and does not focus it
- test-added  app/src/reveal.test.ts#a dock, app, or menu activation focuses the window
  - app/src/reveal.test.ts  a dock, app, or menu activation focuses the window
- test-added  app/src/reveal.test.ts#a minimized window is restored only when the user activates the app
  - app/src/reveal.test.ts  a minimized window is restored only when the user activates the app
- test-added  app/src/reveal.test.ts#a missing or destroyed window is left alone
  - app/src/reveal.test.ts  a missing or destroyed window is left alone
- test-added  app/src/reveal.test.ts#headless never shows a window
  - app/src/reveal.test.ts  headless never shows a window

#### deeplinks  Deep links

- symbol-added  src/cbi/open_link.py#_shell32
  - src/cbi/open_link.py  _shell32
- symbol-added  src/cbi/open_link.py#_shell_execute_no_activate
  - src/cbi/open_link.py  _shell_execute_no_activate
- symbol-added  src/cbi/open_link.py#_windows_start
  - src/cbi/open_link.py  _windows_start
- symbol-added  tests/test_open.py#_install_shell32
  - tests/test_open.py  _install_shell32
- symbol-changed  body  src/cbi/open_link.py#_mac_open
  - src/cbi/open_link.py  _mac_open
- symbol-changed  body  src/cbi/open_link.py#_windows_open
  - src/cbi/open_link.py  _windows_open
- symbol-changed  body  src/cbi/open_link.py#_xdg_open
  - src/cbi/open_link.py  _xdg_open
- symbol-changed  body  src/cbi/open_link.py#open_url
  - src/cbi/open_link.py  open_url
- symbol-changed  body  tests/test_open.py#_open
  - tests/test_open.py  _open
- untested  tests/test_open.py#_open
  - tests/test_open.py  _open
- test-removed  tests/test_open.py#test_open_url_falls_back_to_start_when_startfile_is_missing
  - tests/test_open.py  test_open_url_falls_back_to_start_when_startfile_is_missing
- test-removed  tests/test_open.py#test_open_url_startfile_error_is_a_failure
  - tests/test_open.py  test_open_url_startfile_error_is_a_failure
- test-removed  tests/test_open.py#test_open_url_uses_open_on_macos
  - tests/test_open.py  test_open_url_uses_open_on_macos
- test-removed  tests/test_open.py#test_open_url_uses_startfile_on_windows
  - tests/test_open.py  test_open_url_uses_startfile_on_windows
- test-removed  tests/test_open.py#test_open_url_uses_xdg_open_on_linux
  - tests/test_open.py  test_open_url_uses_xdg_open_on_linux
- test-added  tests/test_open.py#test_open_url_does_not_activate_on_windows
  - tests/test_open.py  test_open_url_does_not_activate_on_windows
- test-added  tests/test_open.py#test_open_url_falls_back_to_start_when_shell32_is_missing
  - tests/test_open.py  test_open_url_falls_back_to_start_when_shell32_is_missing
- test-added  tests/test_open.py#test_open_url_shell_execute_error_is_a_failure
  - tests/test_open.py  test_open_url_shell_execute_error_is_a_failure
- test-added  tests/test_open.py#test_open_url_uses_open_g_on_macos
  - tests/test_open.py  test_open_url_uses_open_g_on_macos
- test-added  tests/test_open.py#test_open_url_uses_xdg_open_without_an_activation_token
  - tests/test_open.py  test_open_url_uses_xdg_open_without_an_activation_token

## 2026-10-09 cee0cb711406 by joshuavial

### structural diff

#### shell  Desktop shell

- env-read  CBI_ALLOW_VISIBLE_SMOKE
  - app/test/smoke.mjs  smoke.mjs

## 2026-10-09 15c055f55e5c by joshuavial

### structural diff

#### packaging  App packaging

- concept-added  App packaging
  - app/scripts/copy-assets.mjs  copy-assets.mjs
- relationship-added  App packaging -> Desktop shell  copies the window HTML and CSS into dist for the desktop app  calls 0  imports 0

#### release-notes  Release notes

- concept-added  Release notes
  - .github/changelog_notes.py  changelog_notes.py
  - tests/test_changelog_notes.py  test_changelog_notes.py
- symbol-added  .github/changelog_notes.py#main
  - .github/changelog_notes.py  main
- symbol-added  .github/changelog_notes.py#section
  - .github/changelog_notes.py  section
- symbol-added  tests/test_changelog_notes.py#_notes
  - tests/test_changelog_notes.py  _notes
- test-added  tests/test_changelog_notes.py#test_missing_section_exits
  - tests/test_changelog_notes.py  test_missing_section_exits
- test-added  tests/test_changelog_notes.py#test_repo_changelog_has_the_release_notes
  - tests/test_changelog_notes.py  test_repo_changelog_has_the_release_notes
- test-added  tests/test_changelog_notes.py#test_section_is_one_version
  - tests/test_changelog_notes.py  test_section_is_one_version

#### deeplinks  Deep links

- relationship-volume  Deep links -> Desktop shell  resolves the project, worktree and comparison the link names  calls 5 -> 6  imports 2 -> 3
  - app/src/deeplink.ts  deeplink.ts
  - app/src/deeplink.ts  openComparison
  - app/src/deeplink.ts  realGh
  - app/src/deeplink.ts  validateOpen
- symbol-added  app/src/deeplink.ts#isAbsolutePath
  - app/src/deeplink.ts  isAbsolutePath
- symbol-added  src/cbi/open_link.py#_windows_open
  - src/cbi/open_link.py  _windows_open
- symbol-added  src/cbi/open_link.py#_xdg_open
  - src/cbi/open_link.py  _xdg_open
- symbol-added  src/cbi/open_link.py#open_url
  - src/cbi/open_link.py  open_url
- symbol-added  tests/test_open.py#_Run
  - tests/test_open.py  _Run
- symbol-added  tests/test_open.py#_Run.__init__
  - tests/test_open.py  __init__
- symbol-changed  body  app/src/deeplink.ts#realGh
  - app/src/deeplink.ts  realGh
- symbol-changed  body  src/cbi/open_link.py#_run
  - src/cbi/open_link.py  _run
- symbol-changed  body  src/cbi/open_link.py#run
  - src/cbi/open_link.py  run
- symbol-changed  signature+body  app/src/deeplink.ts#parseOpenUrl
  - app/src/deeplink.ts  parseOpenUrl
- test-added  tests/test_open.py#test_open_url_falls_back_to_start_when_startfile_is_missing
  - tests/test_open.py  test_open_url_falls_back_to_start_when_startfile_is_missing
- test-added  tests/test_open.py#test_open_url_startfile_error_is_a_failure
  - tests/test_open.py  test_open_url_startfile_error_is_a_failure
- test-added  tests/test_open.py#test_open_url_uses_open_on_macos
  - tests/test_open.py  test_open_url_uses_open_on_macos
- test-added  tests/test_open.py#test_open_url_uses_startfile_on_windows
  - tests/test_open.py  test_open_url_uses_startfile_on_windows
- test-added  tests/test_open.py#test_open_url_uses_xdg_open_on_linux
  - tests/test_open.py  test_open_url_uses_xdg_open_on_linux

#### github.com/joshuavial/codebase-inspector:deployable:build  build

- deployable-added  build

#### cli  Command line

- env-unread  CBI_SNAPSHOT_DIR
  - app/src/editor.ts  snapshotCache
  - src/cbi/editor.py  snapshot_cache
- symbol-added  src/cbi/cli.py#package_version
  - src/cbi/cli.py  package_version
- symbol-added  src/cbi/editor.py#_join_program
  - src/cbi/editor.py  _join_program
- symbol-added  src/cbi/editor.py#_path_sep
  - src/cbi/editor.py  _path_sep
- symbol-added  src/cbi/editor.py#_popen_kwargs
  - src/cbi/editor.py  _popen_kwargs
- symbol-added  src/cbi/editor.py#_where_program
  - src/cbi/editor.py  _where_program
- symbol-added  src/cbi/editor.py#command_names
  - src/cbi/editor.py  command_names
- symbol-changed  body  src/cbi/cli.py#build_parser
  - src/cbi/cli.py  build_parser
- symbol-changed  signature+body  src/cbi/editor.py#command_argv
  - src/cbi/editor.py  command_argv
- symbol-changed  signature+body  src/cbi/editor.py#find_program
  - src/cbi/editor.py  find_program
- symbol-changed  signature+body  src/cbi/editor.py#launch
  - src/cbi/editor.py  launch
- symbol-changed  signature+body  src/cbi/editor.py#resolve_program
  - src/cbi/editor.py  resolve_program
- symbol-changed  signature+body  src/cbi/editor.py#snapshot_cache
  - src/cbi/editor.py  snapshot_cache
- test-added  tests/test_cli.py#test_version_matches_the_package
  - tests/test_cli.py  test_version_matches_the_package
- test-added  tests/test_editor.py#test_snapshot_cache_follows_the_platform
  - tests/test_editor.py  test_snapshot_cache_follows_the_platform
- test-added  tests/test_editor.py#test_windows_editor_lookup_prefers_code_cmd
  - tests/test_editor.py  test_windows_editor_lookup_prefers_code_cmd

#### shell  Desktop shell

- env-unread  CBI_SNAPSHOT_DIR
  - app/src/editor.ts  snapshotCache
  - src/cbi/editor.py  snapshot_cache
- symbol-added  app/src/editor.ts#detachedArgv
  - app/src/editor.ts  detachedArgv
- symbol-added  app/src/editor.ts#quoteWin
  - app/src/editor.ts  quoteWin
- symbol-added  app/src/fast-open.ts#fileUri
  - app/src/fast-open.ts  fileUri
- symbol-added  app/src/which.ts#canRun
  - app/src/which.ts  canRun
- symbol-added  app/src/which.ts#clearCommandCache
  - app/src/which.ts  clearCommandCache
- symbol-added  app/src/which.ts#commandExecutable
  - app/src/which.ts  commandExecutable
- symbol-added  app/src/which.ts#commandNames
  - app/src/which.ts  commandNames
- symbol-added  app/src/which.ts#findOnPath
  - app/src/which.ts  findOnPath
- symbol-added  app/src/which.ts#joinCommand
  - app/src/which.ts  joinCommand
- symbol-added  app/src/which.ts#missingGit
  - app/src/which.ts  missingGit
- symbol-added  app/src/which.ts#pathSeparator
  - app/src/which.ts  pathSeparator
- symbol-added  app/src/which.ts#whereCommand
  - app/src/which.ts  whereCommand
- symbol-changed  body  app/src/editor.ts#gitShowBlob
  - app/src/editor.ts  gitShowBlob
- symbol-changed  body  app/src/editor.ts#gitWorktrees
  - app/src/editor.ts  gitWorktrees
- symbol-changed  body  app/src/editor.ts#launchEditor
  - app/src/editor.ts  launchEditor
- symbol-changed  body  app/src/editor.ts#repoSnapshotName
  - app/src/editor.ts  repoSnapshotName
- symbol-changed  body  app/src/fast-open.ts#sqliteArgs
  - app/src/fast-open.ts  sqliteArgs
- symbol-changed  body  app/src/main.ts#verifyCommit
  - app/src/main.ts  verifyCommit
- symbol-changed  body  app/src/model-read.ts#querySqlite
  - app/src/model-read.ts  querySqlite
- symbol-changed  body  app/src/project.ts#realGit
  - app/src/project.ts  realGit
- symbol-changed  signature  app/src/editor.ts#resolveProgram
  - app/src/editor.ts  resolveProgram
- symbol-changed  signature+body  app/src/cbi-bin.ts#findCbi
  - app/src/cbi-bin.ts  findCbi
- symbol-changed  signature+body  app/src/editor.ts#commandArgv
  - app/src/editor.ts  commandArgv
- symbol-changed  signature+body  app/src/editor.ts#findProgram
  - app/src/editor.ts  findProgram
- symbol-changed  signature+body  app/src/editor.ts#snapshotCache
  - app/src/editor.ts  snapshotCache
- untested  app/src/main.ts#verifyCommit
  - app/src/main.ts  verifyCommit
- untested  app/src/model-read.ts#querySqlite
  - app/src/model-read.ts  querySqlite
- test-added  app/src/cbi-bin.test.ts#windows searches PATH for cbi.exe, then the user local bin, then where
  - app/src/cbi-bin.test.ts  windows searches PATH for cbi.exe, then the user local bin, then where
- test-added  app/src/editor.test.ts#windows looks up code.cmd and caches snapshots under LocalAppData
  - app/src/editor.test.ts  windows looks up code.cmd and caches snapshots under LocalAppData
- test-added  app/src/which.test.ts#a missing git message names the platform
  - app/src/which.test.ts  a missing git message names the platform
- test-added  app/src/which.test.ts#command names and PATH separators follow the platform
  - app/src/which.test.ts  command names and PATH separators follow the platform
- test-added  app/src/which.test.ts#findOnPath on windows prefers exe, then where, and does not use where elsewhere
  - app/src/which.test.ts  findOnPath on windows prefers exe, then where, and does not use where elsewhere

#### render  Rendering

- symbol-added  src/cbi/render.py#_popen_kwargs
  - src/cbi/render.py  _popen_kwargs
- symbol-added  src/cbi/render.py#_windows_chrome_roots
  - src/cbi/render.py  _windows_chrome_roots
- symbol-changed  body  src/cbi/render.py#_capture
  - src/cbi/render.py  _capture
- symbol-changed  body  src/cbi/render.py#_kill_group
  - src/cbi/render.py  _kill_group
- symbol-changed  body  src/cbi/render.py#application_dirs
  - src/cbi/render.py  application_dirs
- symbol-changed  signature+body  src/cbi/render.py#find_chrome
  - src/cbi/render.py  find_chrome
- test-added  tests/test_render.py#test_chrome_process_flags_on_windows
  - tests/test_render.py  test_chrome_process_flags_on_windows
- test-added  tests/test_render.py#test_find_chrome_on_windows_uses_program_files_then_path
  - tests/test_render.py  test_find_chrome_on_windows_uses_program_files_then_path

#### viewer  Static viewer

- symbol-added  src/cbi/viewer/open-editor.js#normalizeRoot
  - src/cbi/viewer/open-editor.js  normalizeRoot
- symbol-added  tests/test_editor_url.py#href
  - tests/test_editor_url.py  href
- symbol-changed  body  src/cbi/build.py#_project_root
  - src/cbi/build.py  _project_root
- symbol-changed  body  src/cbi/viewer/open-editor.js#editorHref
  - src/cbi/viewer/open-editor.js  editorHref
- symbol-changed  body  src/cbi/viewer/open-editor.js#projectRoot
  - src/cbi/viewer/open-editor.js  projectRoot
- untested  src/cbi/viewer/open-editor.js#editorHref
  - src/cbi/viewer/open-editor.js  editorHref
- untested  src/cbi/viewer/open-editor.js#projectRoot
  - src/cbi/viewer/open-editor.js  projectRoot
- test-added  tests/test_editor_url.py#test_unix_editor_href_keeps_the_leading_slash
  - tests/test_editor_url.py  test_unix_editor_href_keeps_the_leading_slash
- test-added  tests/test_editor_url.py#test_windows_drive_letter_is_not_encoded
  - tests/test_editor_url.py  test_windows_drive_letter_is_not_encoded
- test-added  tests/test_editor_url.py#test_windows_file_url_pathname_drops_the_extra_slash
  - tests/test_editor_url.py  test_windows_file_url_pathname_drops_the_extra_slash
