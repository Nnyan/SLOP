<template>
<div class="p-4 max-w-4xl mx-auto w-full">

    <!-- Header: title + search + selection actions — all one row -->
    <div class="flex items-center gap-3 mb-3">
      <div class="shrink-0">
        <h1 class="page-title leading-none">Catalog</h1>
        <p class="text-xs text-slate-400 mt-0.5">
          {{ loading ? 'Loading…' : totalVisible + ' apps' }}
          <RouterLink to="/settings?tab=system" class="text-amber-600 hover:text-amber-700 ml-2">+ custom</RouterLink>
        </p>
      </div>
      <div class="relative flex-1 max-w-xs">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-300 text-sm pointer-events-none">⌕</span>
        <input v-model="search" type="text" placeholder="Search apps…"
          class="input pl-8 w-full" @input="onSearch" />
      </div>
      <!-- Selection actions -->
      <Transition enter-from-class="opacity-0 scale-95" enter-active-class="transition-all duration-150"
        leave-to-class="opacity-0 scale-95" leave-active-class="transition-all duration-150">
        <div v-if="selectedKeys.size > 0" class="flex items-center gap-2 shrink-0">
          <span class="text-xs text-slate-500">{{ selectedKeys.size }} selected</span>
          <button @click="clearSelection" class="btn-secondary btn-sm text-xs">✕</button>
          <button @click="openPreflight" :disabled="batchInstalling" class="btn-primary btn-sm text-xs">
            Install {{ selectedKeys.size }} →
          </button>
        </div>
      </Transition>
    </div>

    <!-- Category pills — tight, single row -->
    <div class="flex gap-1 flex-wrap mb-4 items-center">
      <button :class="['pill', activeCats.size === 0 ? 'pill-active' : '']" @click="resetCats">All</button>
      <button v-for="cat in Object.keys(allApps)" :key="cat"
        :class="['pill', activeCats.has(cat) ? 'pill-active' : '']"
        @click="toggleCat(cat)">
        {{ CAT_LABELS[cat] || cat }}
        <span class="opacity-50 text-xs">{{ allApps[cat]?.length || 0 }}</span>
      </button>
      <button v-if="activeCats.size > 0" @click="resetCats" class="text-xs text-slate-400 hover:text-slate-600 ml-1">✕</button>
    </div>

    <!-- App list — compact rows grouped by category -->
    <div style="min-height: 60vh">

      <!-- Loading skeleton -->
      <div v-if="loading" class="space-y-px">
        <div v-for="n in 12" :key="n"
          class="flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-100 animate-pulse">
          <div class="w-6 h-6 rounded bg-slate-100 shrink-0"/>
          <div class="h-3 bg-slate-100 rounded flex-1 max-w-32"/>
          <div class="h-3 bg-slate-100 rounded w-16 ml-auto"/>
          <div class="h-5 bg-slate-100 rounded w-12"/>
        </div>
      </div>

      <!-- App rows by category -->
      <template v-else v-for="(entries, cat) in filtered" :key="cat">
        <div class="flex items-center gap-2 mt-4 mb-1 first:mt-0">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">{{ CAT_LABELS[cat] || cat }}</span>
          <span class="text-xs text-slate-300">{{ entries.length }}</span>
        </div>

        <!-- One card containing all rows for this category -->
        <div class="card overflow-hidden">
          <div v-for="(app, idx) in entries" :key="app.key"
            @click="toggleSelect(app.key)"
            :class="[
              'flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors',
              idx < entries.length - 1 ? 'border-b border-slate-50' : '',
              installing === app.key
                ? 'bg-amber-50'
                : selectedKeys.has(app.key)
                  ? 'bg-sky-50'
                  : isInstalled(app.key)
                    ? 'bg-slate-50/60'
                    : 'hover:bg-slate-50'
            ]">

            <!-- Selection checkmark -->
            <div v-if="selectedKeys.has(app.key)"
              class="w-4 h-4 rounded-full bg-sky-500 flex items-center justify-center shrink-0">
              <span class="text-white text-xs leading-none font-bold">✓</span>
            </div>

            <!-- App icon -->
            <div :class="['w-6 h-6 rounded flex items-center justify-center shrink-0 overflow-hidden',
              selectedKeys.has(app.key) ? '' : 'bg-slate-100']">
              <img :src="iconUrl(app)" :alt="app.display_name"
                class="w-5 h-5 object-contain"
                @error="(e: Event) => { const t = e.target as HTMLImageElement; t.style.display='none'; (t.nextElementSibling as HTMLElement).style.display='block' }" />
              <span class="text-sm hidden">{{ app.icon }}</span>
            </div>

            <!-- Name + badges -->
            <div class="flex-1 min-w-0 flex items-center gap-2">
              <span :class="['text-sm font-medium truncate',
                isInstalled(app.key) ? 'text-slate-500' : 'text-slate-800']">
                {{ app.display_name }}
              </span>
              <span v-if="(app as any).is_new"
                class="text-xs px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium shrink-0">NEW</span>
              <span v-if="sourceIssues.has(app.key)"
                class="text-xs text-red-500 shrink-0" title="Source URL issue">⚠</span>
            </div>

            <!-- Actions -->
            <div class="flex items-center gap-2 shrink-0" @click.stop>
              <RouterLink v-if="isInstalled(app.key)" :to="`/apps/${app.key}`"
                class="text-xs text-slate-400 hover:text-slate-600">Manage</RouterLink>
              <button v-if="isInstalled(app.key)"
                class="text-xs px-2.5 py-0.5 rounded border border-slate-200 text-slate-500 hover:border-slate-300 transition-colors"
                :disabled="installing === app.key"
                @click="singleInstall(app)">
                <span v-if="installing === app.key" class="flex items-center gap-1">
                  <span class="inline-block w-2.5 h-2.5 border border-slate-400 border-t-transparent rounded-full animate-spin"/>
                  Installing…
                </span>
                <span v-else>Reinstall</span>
              </button>
              <button v-else
                class="text-xs px-2.5 py-0.5 rounded border border-slate-200 text-slate-500 hover:bg-orange-500 hover:border-orange-500 hover:text-white transition-colors"
                :class="{ 'opacity-50 cursor-wait': installing === app.key }"
                :disabled="installing === app.key"
                @click="singleInstall(app)">
                <span v-if="installing === app.key" class="flex items-center gap-1">
                  <span class="inline-block w-2.5 h-2.5 border border-orange-300 border-t-transparent rounded-full animate-spin"/>
                  Installing…
                </span>
                <span v-else>Install</span>
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- Empty state -->
      <div v-if="!loading && totalVisible === 0" class="text-center py-16 text-slate-400 text-sm">
        No apps match "{{ search }}"
      </div>

    </div><!-- /min-height wrapper -->

  </div><!-- /root -->

  <!-- ── Single-app install modal ── -->
  <Teleport to="body">
    <div v-if="installTarget" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="installTarget = null"/>
      <div class="relative card w-full max-w-md mx-4 card-body">

        <!-- Header -->
        <div class="flex items-center gap-3 mb-4">
          <span class="text-2xl">{{ installTarget.icon }}</span>
          <div>
            <h3 class="font-semibold text-slate-900">{{ installTarget.display_name }}</h3>
            <p class="text-xs text-slate-400 capitalize">{{ installTarget.category }}</p>
          </div>
        </div>

        <!-- Description -->
        <p class="text-sm text-slate-500 mb-4 leading-relaxed">{{ installTarget.description }}</p>

        <!-- Options (only when not installing) -->
        <template v-if="!installing">
          <div class="space-y-3 mb-4">
            <div v-if="installTarget.web_port">
              <label class="text-xs font-medium text-slate-600">Host port override <span class="text-slate-400">(optional)</span></label>
              <input v-model.number="installOpts.host_port" type="number" placeholder="leave blank for default"
                class="input w-full mt-1 text-sm" />
            </div>
          </div>

          <div v-if="installError" class="rounded-lg bg-red-50 border border-red-100 p-3 text-xs text-red-700 mb-4">
            {{ installError }}
          </div>

          <div class="flex gap-3">
            <button @click="installTarget = null" class="btn-secondary flex-1">Cancel</button>
            <button @click="confirmInstall" class="btn-primary flex-1">Install</button>
          </div>
        </template>

        <!-- Progress (while installing) -->
        <template v-else>
          <div class="mb-3">
            <div class="flex items-center justify-between text-xs text-slate-500 mb-1">
              <span>{{ installTimeLabel }}</span>
              <span>{{ installProgress }}%</span>
            </div>
            <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div class="h-full bg-orange-500 rounded-full transition-all duration-300"
                   :style="{ width: installProgress + '%' }" />
            </div>
          </div>

          <div v-if="installSteps.length" class="space-y-1 max-h-40 overflow-y-auto mb-3">
            <div v-for="step in installSteps" :key="step.name"
              class="flex items-center gap-2 text-xs text-slate-500">
              <span :class="[
                'status-dot',
                step.status === 'ok' ? 'bg-green-500' :
                step.status === 'warning' ? 'bg-amber-400' :
                step.status === 'error' ? 'bg-red-500' :
                step.status === 'skipped' ? 'bg-slate-300' : 'bg-blue-400'
              ]"/>
              {{ step.message || step.name }}
            </div>
          </div>

          <div v-if="installError" class="rounded-lg bg-red-50 border border-red-100 p-3 text-xs text-red-700 mb-3">
            {{ installError }}
            <button @click="installTarget = null" class="block mt-2 text-red-500 hover:text-red-700 font-medium">Dismiss</button>
          </div>

          <p v-else class="text-xs text-slate-400 text-center">Installing — please wait…</p>
        </template>

      </div>
    </div>
  </Teleport>

</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { RouterLink } from 'vue-router'
import { catalog, apps as appsApi } from '../api/client'
import { catalogCache, installedCache, setCatalogCache, setInstalledCache } from '../catalogCache'
import { useToast } from '@/composables/useToast'
import type { CatalogEntry, AppStatus } from '../api/client'

const toast = useToast()

const CAT_LABELS: Record<string, string> = {
  arr: 'Arr', media: 'Media', ai: 'AI',
  monitoring: 'Monitoring', productivity: 'Productivity', tools: 'Tools',
}

const QUICK_STACKS = [
  { name: 'arr', label: '⚡ Full arr stack', keys: ['prowlarr', 'sonarr', 'radarr', 'bazarr', 'seerr'] },
  { name: 'debrid', label: '🌩 Debrid stack', keys: ['prowlarr', 'sonarr', 'radarr', 'decypharr', 'seerr'] },
  { name: 'minimal', label: '🎬 Minimal', keys: ['sonarr', 'radarr', 'prowlarr'] },
  { name: 'media', label: '📺 Media servers', keys: ['plex', 'jellyfin', 'audiobookshelf'] },
]

const search = ref('')
// Use shared cache module — may already be primed by App.vue prefetch
const allApps = ref<Record<string, CatalogEntry[]>>(catalogCache ?? {})
const loading = ref(catalogCache === null)
const installedKeys = ref<Set<string>>(new Set())
const selectedKeys = ref<Set<string>>(new Set())
const activeCats = ref<Set<string>>(new Set())

// Active interval/timer refs for cleanup
let _activePoll: ReturnType<typeof setInterval> | null = null
let _lintTimer: ReturnType<typeof setTimeout> | null = null

// Single install
const installing = ref<string | null>(null)
const installTarget = ref<CatalogEntry | null>(null)
const installOpts = ref({ host_port: null as number | null, vpn_scoped: false })
const installError = ref<string | null>(null)
const installSteps = ref<any[]>([])
const installStepsDone = computed(() => installSteps.value.filter(s => s.status === 'ok' || s.status === 'warning').length)
const installStepsTotal = computed(() => Math.max(installSteps.value.length, 4))

// Time-based progress — fills over expected duration regardless of step count
const installProgress = ref(5)
const installTimeLabel = ref('Starting…')
let _installTimer: ReturnType<typeof setInterval> | null = null

function startInstallProgress(expectedSeconds: number) {
  installProgress.value = 5
  installTimeLabel.value = 'Starting…'
  if (_installTimer) clearInterval(_installTimer)
  const start = Date.now()
  const total = expectedSeconds * 1000
  _installTimer = setInterval(() => {
    const elapsed = Date.now() - start
    const pct = Math.min(90, 5 + (elapsed / total) * 85) // fills to 90% max
    const rem = Math.max(0, Math.round((total - elapsed) / 1000))
    installProgress.value = Math.round(pct)
    installTimeLabel.value = elapsed < 3000
      ? 'Starting…'
      : rem > 5
        ? `~${rem}s remaining`
        : 'Almost done…'
  }, 250)
}

function finishInstallProgress() {
  if (_installTimer) { clearInterval(_installTimer); _installTimer = null }
  installProgress.value = 100
  installTimeLabel.value = 'Complete'
}

function stopInstallProgress() {
  if (_installTimer) { clearInterval(_installTimer); _installTimer = null }
}

// Batch install
const showPreflight = ref(false)
const preflightResult = ref<any>(null)
const batchInstalling = ref(false)
const showYamlLinter = ref(false)
const customTab = ref('Paste YAML')
const githubUrl = ref('')
const githubResult = ref<any>(null)
const yamlInput = ref('')
const lintResult = ref<any>(null)
// _lintTimer moved inside component via onUnmounted
const batchProgress = ref<{ key: string; status: string; message: string }[]>([])

const filtered = computed(() => {
  const q = search.value.toLowerCase().trim()
  const result: Record<string, CatalogEntry[]> = {}
  for (const [cat, entries] of Object.entries(allApps.value)) {
    if (activeCats.value.size > 0 && !activeCats.value.has(cat)) continue
    const visible = entries.filter(app =>
      !q ||
      app.display_name.toLowerCase().includes(q) ||
      app.description.toLowerCase().includes(q) ||
      (app.tags || []).some((t: string) => t.toLowerCase().includes(q))
    )
    if (visible.length) result[cat] = visible
  }
  return result
})

const totalVisible = computed(() =>
  Object.values(filtered.value).reduce((s, a) => s + a.length, 0)
)

function truncateDesc(desc: string): string {
  const words = desc.split(' ')
  return words.length > 7 ? words.slice(0, 7).join(' ') + '…' : desc
}

function appIcon(key: string): string {
  for (const entries of Object.values(allApps.value)) {
    const a = entries.find(e => e.key === key)
    if (a) return a.icon || '📦'
  }
  return '📦'
}

function appName(key: string): string {
  for (const entries of Object.values(allApps.value)) {
    const a = entries.find(e => e.key === key)
    if (a) return a.display_name
  }
  return key
}

function iconUrl(app: any): string {
  const name = (app.dashboard_icon || app.key).replace(/_/g, '-').toLowerCase()
  return `https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons/png/${name}.png`
}

function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''
}

function isInstalled(key: string) { return installedKeys.value.has(key) }

const sourceIssues = ref<Set<string>>(new Set())

const selectedApps = computed(() => {
  const all: any[] = Object.values(allApps.value).flat()
  return [...selectedKeys.value].map(k => all.find((a: any) => a.key === k)).filter(Boolean)
})

async function loadSourceIssues() {
  try {
    const r = await fetch('/api/v1/health/sources')
    if (r.ok) {
      const d = await r.json()
      sourceIssues.value = new Set(
        (d.issues || [])
          .filter((i: any) => i.source_type === 'docker_image')
          .map((i: any) => i.resource_key)
      )
    }
  } catch {}
}
function onSearch() {}

function toggleCat(cat: string) {
  activeCats.value.has(cat) ? activeCats.value = new Set([...activeCats.value].filter(c => c !== cat)) : activeCats.value = new Set([...activeCats.value, cat])
}
function resetCats() { activeCats.value = new Set() }

function toggleSelect(key: string) {
  if (isInstalled(key)) return
  selectedKeys.value.has(key) ? selectedKeys.value = new Set([...selectedKeys.value].filter(k => k !== key)) : selectedKeys.value = new Set([...selectedKeys.value, key])
}

function clearSelection() { selectedKeys.value = new Set() }

function applyStack(stack: { keys: string[] }) {
  clearSelection()
  for (const key of stack.keys) {
    if (!isInstalled(key)) selectedKeys.value = new Set([...selectedKeys.value, key])
  }
}

function lintYaml() {
  if (_lintTimer) clearTimeout(_lintTimer)
  if (!yamlInput.value.trim()) { lintResult.value = null; return }
  _lintTimer = setTimeout(async () => {
    try {
      const res = await fetch('/api/v1/apps/lint-compose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ yaml: yamlInput.value }),
      })
      lintResult.value = await res.json()
    } catch (e) {
      lintResult.value = { valid: false, errors: [String(e)], warnings: [] }
    }
  }, 400) // 400ms debounce
}

async function installFromYaml() {
  if (!lintResult.value?.valid || !lintResult.value?.manifest_preview) return
  const preview = lintResult.value.manifest_preview
  installing.value = '__yaml__'
  try {
    const res = await fetch('/api/v1/apps/install-custom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ manifest: preview, compose_yaml: yamlInput.value }),
    })
    if (res.ok) {
      toast.success(`${preview.display_name} install started.`)
      showYamlLinter.value = false
      yamlInput.value = ''
      lintResult.value = null
    } else {
      const err = await res.json()
      toast.error('Install failed.', err.detail ?? String(err))
    }
  } catch (e) {
    toast.error('Install failed.', String(e))
  } finally {
    installing.value = null
  }
}

async function installFromGitHub() {
  if (!githubUrl.value) return
  installing.value = '__github__'
  githubResult.value = null
  try {
    const res = await fetch('/api/v1/apps/install-from-github', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: githubUrl.value }),
    })
    const data = await res.json()
    githubResult.value = data
    if (data.ok) toast.success(`Manifest fetched: ${data.key}`)
    else toast.error('Fetch failed.', data.detail ?? '')
  } catch (e) {
    githubResult.value = { ok: false, message: String(e) }
  } finally {
    installing.value = null
  }
}

async function openPreflight() {
  showPreflight.value = true
  preflightResult.value = null
  batchProgress.value = []
  try {
    const res = await fetch('/api/v1/apps/batch/preflight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keys: [...selectedKeys.value] }),
    })
    preflightResult.value = await res.json()
  } catch (e) {
    toast.error('Could not run pre-flight check.')
  }
}

async function runBatchInstall() {
  if (!preflightResult.value?.can_proceed) return
  batchInstalling.value = true
  batchProgress.value = (preflightResult.value.install_order || []).map((k: string) => ({
    key: k, status: 'pending', message: 'Waiting…'
  }))

  try {
    await fetch('/api/v1/apps/batch/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keys: [...selectedKeys.value] }),
    })

    // Poll each app
    for (const item of batchProgress.value) {
      item.status = 'running'
      item.message = 'Installing…'
      const deadline = Date.now() + 600_000
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 800))
        try {
          const prog = await appsApi.installProgress(item.key)
          if (prog.done) {
            item.status = prog.ok ? 'ok' : 'error'
            item.message = prog.ok ? 'Installed' : (prog.error || 'Failed')
            if (prog.ok) installedKeys.value.add(item.key)
            break
          }
        } catch {}
      }
    }

    const failed = batchProgress.value.filter(i => i.status === 'error').length
    const installed = batchProgress.value.filter(i => i.status === 'ok').length
    if (failed === 0) {
      toast.success(`${installed} app${installed !== 1 ? 's' : ''} installed successfully.`)
      clearSelection()
      setTimeout(() => { showPreflight.value = false }, 2000)
    } else {
      toast.warn(`${installed} installed, ${failed} failed.`)
    }
  } catch (e) {
    toast.error('Batch install failed.', e instanceof Error ? e.message : String(e))
  } finally {
    batchInstalling.value = false
  }
}

function singleInstall(app: CatalogEntry) {
  installTarget.value = app
  installOpts.value = { host_port: null, vpn_scoped: false }
  installError.value = null
  installSteps.value = []
}

async function confirmInstall() {
  if (!installTarget.value) return
  const key = installTarget.value.key
  installing.value = key
  installError.value = null
  installSteps.value = []
  const graceSecs = (installTarget.value as any).start_grace_s || 60
  startInstallProgress(graceSecs + 30) // grace + pull time estimate

  try {
    const opts: Record<string, unknown> = {}
    if (installOpts.value.host_port) opts.host_port = installOpts.value.host_port
    if (installOpts.value.vpn_scoped) opts.vpn_scoped = true
    await appsApi.install(key, opts)

    _activePoll = setInterval(async () => {
      try {
        const progress = await appsApi.installProgress(key)
        installSteps.value = progress.steps ?? []
        if (progress.done) {
          clearInterval(_activePoll!); _activePoll = null
          if (progress.ok) {
            installedKeys.value.add(key)
            finishInstallProgress()
            toast.success(`${installTarget.value?.display_name ?? key} installed.`)
            setTimeout(() => { installTarget.value = null }, 1500)
          } else {
            installError.value = progress.error ?? 'Installation failed.'
            stopInstallProgress()
            toast.error(`Failed to install ${key}.`, installError.value, 8000)
          }
          installing.value = null
        }
      } catch { clearInterval(_activePoll!); _activePoll = null; installing.value = null }
    }, 600)
    setTimeout(() => {
      clearInterval(_activePoll!); _activePoll = null
      if (installing.value === key) {
        installing.value = null
        installError.value = `Install timed out after 5 minutes. The container may still be starting. Check: docker logs ${key}`
        stopInstallProgress()
        toast.error(`Install timed out for ${key}.`, installError.value, 8000)
      }
    }, 300_000)
  } catch (e) {
    installError.value = e instanceof Error ? e.message : String(e)
    stopInstallProgress()
    installing.value = null
  }
}

onUnmounted(() => {
  if (_activePoll) clearInterval(_activePoll)
  if (_lintTimer) clearTimeout(_lintTimer)
  if (_installTimer) clearInterval(_installTimer)
})

onMounted(async () => {
  loadSourceIssues()

  // If cache already primed (by App.vue prefetch or prior visit), render instantly
  if (catalogCache) {
    allApps.value = catalogCache
    if (installedCache) installedKeys.value = installedCache
    loading.value = false
    // Refresh installed list in background
    appsApi.list().then(list => {
      setInstalledCache(new Set(list.map((a: AppStatus) => a.key)))
      installedKeys.value = installedCache!
    }).catch(() => {})
    return
  }

  // Cache not ready — load both in parallel, show skeleton until done
  const [catalogData, appList] = await Promise.allSettled([catalog.all(), appsApi.list()])
  if (catalogData.status === 'fulfilled') {
    setCatalogCache(catalogData.value)
    allApps.value = catalogCache!
  }
  if (appList.status === 'fulfilled') {
    setInstalledCache(new Set(appList.value.map((a: AppStatus) => a.key)))
    installedKeys.value = installedCache!
  }
  loading.value = false
})
</script>
<style scoped>
/* ── Card ── */
/* Category pills */
.pill {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 8px; border-radius: 20px;
  font-size: 11px; font-weight: 500;
  cursor: pointer; border: 0.5px solid var(--color-border-secondary);
  background: var(--color-background-primary); color: var(--color-text-secondary);
  transition: all 0.1s; user-select: none;
}
.pill:hover { border-color: var(--color-border-primary); color: var(--color-text-primary); }
.pill-active { background: #F26419; border-color: #F26419; color: #fff; }
</style>