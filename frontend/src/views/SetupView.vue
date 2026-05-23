<template>
  <div class="p-4 max-w-4xl mx-auto w-full">
    <div class="mb-6">
      <h1 class="page-title">Platform Setup</h1>
      <p class="page-subtitle">Configure your platform before installing apps.</p>
    </div>

    <!-- Already configured -->
    <div v-if="platformStore.isReady && !forceSetup" class="card card-body text-center py-10">
      <div class="text-3xl mb-3">✅</div>
      <h2 class="font-semibold text-slate-900">Platform is configured</h2>
      <p class="text-sm text-slate-500 mt-1">Domain: <strong>{{ platformStore.domain }}</strong></p>
      <div class="flex gap-3 justify-center mt-4">
        <RouterLink to="/catalog" class="btn-primary">Install apps →</RouterLink>
        <RouterLink to="/settings?tab=platform" class="btn-secondary">← Settings</RouterLink>
        <button @click="showReset = true" class="btn-secondary text-red-600">Reset platform</button>
      </div>
    </div>

    <template v-else>
      <!-- Stage progress bar -->
      <div ref="stageNavRef" class="flex items-center gap-1.5 mb-6 overflow-x-auto pb-1 scroll-smooth">
        <template v-for="(stage, i) in STAGES" :key="stage.id">
          <button @click="goToStage(i)"
            :disabled="i > maxReachedStage"
            :ref="el => { if (currentStage === i) activeStageBtn = el as HTMLElement }"
            :class="['flex items-center gap-1.5 shrink-0 px-2 py-1 rounded-lg transition-all text-xs',
              currentStage === i ? 'bg-sky-100 text-sky-700 font-semibold' :
              i < currentStage ? 'text-green-600 hover:bg-green-50' :
              i <= maxReachedStage ? 'text-slate-500 hover:bg-slate-50' :
              'text-slate-300 cursor-default']">
            <span :class="['w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold',
              i < currentStage ? 'bg-green-500 text-white' :
              currentStage === i ? 'bg-sky-500 text-white' :
              'bg-slate-100 text-slate-400']">
              {{ i < currentStage ? '✓' : i + 1 }}
            </span>
            <span class="whitespace-nowrap hidden sm:inline">{{ stage.label }}</span>
          </button>
          <div v-if="i < STAGES.length - 1" class="h-px w-3 bg-slate-200 shrink-0"/>
        </template>
      </div>

      <!-- Stage content -->
      <div class="card mb-4">
        <div class="card-header flex items-center justify-between">
          <div>
            <div class="font-semibold text-sm">{{ STAGES[currentStage].label }}</div>
            <div class="text-xs text-slate-400 mt-0.5">{{ STAGES[currentStage].description }}</div>
          </div>
          <span class="text-xs text-slate-400">{{ currentStage + 1 }} / {{ STAGES.length }}</span>
        </div>
        <div class="card-body space-y-4">

          <!-- Stage 0: Prerequisites -->
          <template v-if="currentStage === 0">
            <div class="space-y-3">
              <div class="rounded-lg bg-slate-50 border border-slate-200 p-4">

                <!-- Loading skeleton — shown while fetch is in flight -->
                <div v-if="prereqRunning" class="space-y-3">
                  <div class="flex items-center gap-2 text-xs text-slate-500">
                    <span class="w-3.5 h-3.5 border-2 border-sky-400 border-t-transparent rounded-full animate-spin shrink-0"/>
                    Checking your system…
                  </div>
                  <div v-for="n in 6" :key="n" class="flex items-center gap-3 py-0.5">
                    <div class="w-4 h-3 bg-slate-200 rounded animate-pulse shrink-0"/>
                    <div class="flex-1 flex gap-3">
                      <div :style="{width: (40 + n * 8) + 'px'}" class="h-3 bg-slate-200 rounded animate-pulse"/>
                      <div :style="{width: (30 + n * 5) + 'px'}" class="h-3 bg-slate-100 rounded animate-pulse"/>
                    </div>
                  </div>
                </div>

                <!-- Results -->
                <div v-else-if="prereqChecks.length" class="space-y-1.5">
                  <div v-for="check in prereqChecks" :key="check.key"
                    class="flex items-start gap-2 text-sm py-0.5">
                    <span :class="['shrink-0 mt-0.5 font-bold text-xs w-4 text-center',
                      check.status === 'ok' ? 'text-green-500' :
                      check.status === 'error' ? 'text-red-500' :
                      check.status === 'warning' ? 'text-amber-500' : 'text-slate-400']">
                      {{ check.status === 'ok' ? '✓' : check.status === 'error' ? '✗' : check.status === 'warning' ? '!' : '○' }}
                    </span>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline gap-2 flex-wrap">
                        <span :class="['font-medium text-xs',
                          check.status === 'error' ? 'text-red-700' :
                          check.status === 'warning' ? 'text-amber-700' : 'text-slate-700']">
                          {{ check.label }}
                        </span>
                        <span class="text-slate-400 text-xs font-mono">{{ check.value }}</span>
                      </div>
                      <div v-if="check.detail" class="text-xs text-slate-400 mt-0.5">{{ check.detail }}</div>
                    </div>
                  </div>
                </div>

                <!-- Empty state — before first run (shouldn't be visible long) -->
                <div v-else class="flex items-center gap-2 text-xs text-slate-400 py-1">
                  <span class="text-slate-300">○</span>
                  Click below to check your system
                </div>
              </div>

              <p v-if="prereqError" class="text-sm text-red-600 bg-red-50 rounded-lg p-3">{{ prereqError }}</p>

              <button @click="runPrereqChecks" :disabled="prereqRunning" class="btn-primary btn-sm">
                {{ prereqRunning ? 'Checking…' : prereqChecks.length ? 'Re-check' : 'Run checks' }}
              </button>
            </div>
          </template>

          <!-- Stage 1: Core Config -->
          <template v-if="currentStage === 1">
            <div>
              <label class="label">Base domain <span class="text-red-400">*</span></label>
              <input v-model="form.domain" type="text" placeholder="example.com" class="input" autocomplete="off" />
              <p class="text-xs text-slate-400 mt-1">Apps will be accessible at app.example.com</p>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="label">Config root <span class="text-red-400">*</span></label>
                <input v-model="form.config_root" type="text" class="input" />
              </div>
              <div>
                <label class="label">Media root</label>
                <input v-model="form.media_root" type="text" class="input" />
              </div>
            </div>
            <div class="grid grid-cols-3 gap-3">
              <div>
                <label class="label">PUID
                  <span v-if="systemProfile?.puid_username" class="text-slate-400 font-normal ml-1 text-xs">({{ systemProfile.puid_username }})</span>
                </label>
                <input v-model.number="form.puid" type="number" class="input" />
              </div>
              <div>
                <label class="label">PGID</label>
                <input v-model.number="form.pgid" type="number" class="input" />
              </div>
              <div>
                <label class="label">Timezone</label>
                <input v-model="form.timezone" type="text" class="input" />
              </div>
            </div>
            <div>
              <label class="label">ACME email</label>
              <input v-model="form.acme_email" type="email" class="input"
                :placeholder="form.domain ? 'admin@' + form.domain : 'admin@yourdomain.com'" />
            </div>
          </template>

          <!-- Stage 2: TLS / DNS -->
          <template v-if="currentStage === 2">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="label">Certificate authority</label>
                <select v-model="form.cert_resolver" class="input">
                  <option value="letsencrypt">Let's Encrypt (free, 90-day)</option>
                  <option value="zerossl">ZeroSSL (free, 90-day, separate limits)</option>
                  <option value="buypass">Buypass (free, 180-day)</option>
                  <option value="staging">Staging — testing only</option>
                </select>
              </div>
              <div>
                <label class="label">DNS provider</label>
                <select v-model="form.dns_provider" class="input">
                  <option v-for="(meta, key) in DNS_PROVIDERS" :key="key" :value="key">
                    {{ meta.label }}
                  </option>
                </select>
                <p v-if="DNS_PROVIDERS[form.dns_provider]" class="text-xs text-slate-400 mt-1">
                  Requires: <span class="font-mono">{{ DNS_PROVIDERS[form.dns_provider].vars.join(', ') }}</span>
                  — <a :href="DNS_PROVIDERS[form.dns_provider].link" target="_blank" rel="noopener" class="underline">get credentials ↗</a>
                </p>
              </div>
            </div>
            <div v-if="form.cert_resolver === 'zerossl'"
              class="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3">
              <p class="text-sm text-amber-800">⚠ ZeroSSL requires EAB credentials from
                <a href="https://app.zerossl.com/developer" target="_blank" rel="noopener" class="underline">app.zerossl.com/developer</a>
              </p>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="label text-xs">EAB Key ID</label>
                  <input v-model="form.eab_kid" type="text" class="input font-mono text-xs" placeholder="kid_xxx…" />
                </div>
                <div>
                  <label class="label text-xs">EAB HMAC Key</label>
                  <input v-model="form.eab_hmac" type="password" class="input font-mono text-xs" />
                </div>
              </div>
            </div>
          </template>

          <!-- Stage 3: Infrastructure -->
          <template v-if="currentStage === 3">
            <p class="text-xs text-slate-500">Select infrastructure apps to deploy automatically during setup. These are installed alongside Traefik. You can change them later via the Infrastructure page.</p>
            <div class="space-y-2">
              <div v-for="slot in INFRA_SLOTS" :key="slot.slot" class="border border-slate-200 rounded-lg p-3">
                <div class="mb-2">
                  <div class="text-sm font-medium text-slate-700">{{ slot.label }}</div>
                  <div class="text-xs text-slate-400">{{ slot.description }}</div>
                </div>
                <!-- Multi-select (tunnel) -->
                <div v-if="slot.multi" class="flex gap-2 flex-wrap">
                  <button v-for="opt in slot.options" :key="opt.value"
                    @click="form.tunnels.includes(opt.value) ? form.tunnels.splice(form.tunnels.indexOf(opt.value),1) : form.tunnels.push(opt.value)"
                    :class="['text-xs px-3 py-1.5 rounded-lg border transition-all',
                      form.tunnels.includes(opt.value)
                        ? 'bg-sky-500 text-white border-sky-500'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300']">
                    {{ opt.label }}
                  </button>
                </div>
                <!-- Single-select (everything else) -->
                <div v-else class="flex gap-2 flex-wrap">
                  <button v-for="opt in slot.options" :key="opt.value"
                    @click="form.infra[slot.slot] = opt.value"
                    :class="['text-xs px-3 py-1.5 rounded-lg border transition-all',
                      form.infra[slot.slot] === opt.value
                        ? 'bg-sky-500 text-white border-sky-500'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300']">
                    {{ opt.label }}
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- Stage 4: Quick Stacks -->
          <template v-if="currentStage === 4">
            <p class="text-xs text-slate-500">Select pre-configured app bundles or search for individual apps below.</p>
            <div class="space-y-2">
              <div v-for="stack in QUICK_STACKS_CONFIG" :key="stack.id"
                :class="['border rounded-lg px-3 py-2 cursor-pointer transition-all flex items-center gap-2.5',
                  form.selectedStacks.includes(stack.id)
                    ? 'border-sky-300 bg-sky-50'
                    : systemProfile && (systemProfile.ram_gb || 0) < (STACK_MIN_RAM[stack.id] || 0)
                      ? 'border-amber-200 bg-amber-50 opacity-75'
                      : 'border-slate-200 hover:border-slate-300']"
                @click="toggleStack(stack.id)">
                <input type="checkbox" :checked="form.selectedStacks.includes(stack.id)"
                  class="w-3.5 h-3.5 rounded border-slate-300 shrink-0" readonly />
                <div class="flex-1 min-w-0">
                  <div class="flex items-baseline gap-2">
                    <span class="text-sm font-medium text-slate-800">{{ stack.label }}</span>
                    <span :class="['text-xs', systemProfile && (systemProfile.ram_gb || 99) < (STACK_MIN_RAM[stack.id] || 0)
                      ? 'text-amber-600 font-medium' : 'text-slate-400']">
                      {{ stack.ram_note }}
                      {{ systemProfile && (systemProfile.ram_gb || 99) < (STACK_MIN_RAM[stack.id] || 0) ? '⚠ low RAM' : '' }}
                    </span>
                  </div>
                  <div class="text-xs text-slate-500 truncate">{{ stack.apps.join(' · ') }}</div>
                </div>
              </div>
            </div>
            <!-- Individual app search -->
            <div class="border-t border-slate-100 pt-3 mt-3">
              <label class="label text-xs mb-1">Add individual apps</label>
              <div class="relative">
                <input v-model="appSearch" type="text" class="input text-xs pr-8"
                  placeholder="Search catalog (sonarr, immich, jellyfin…)" />
              </div>
              <div v-if="appSearch && catalogSearchResults.length" class="mt-1.5 space-y-1">
                <button v-for="app in catalogSearchResults" :key="app.key"
                  @click="toggleIndividualApp(app.key)"
                  :class="['w-full flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs text-left transition-all',
                    form.individualApps.includes(app.key)
                      ? 'bg-sky-50 border-sky-300 text-sky-700'
                      : 'bg-white border-slate-200 text-slate-700 hover:border-slate-300']">
                  <span>{{ form.individualApps.includes(app.key) ? '✓' : '+' }}</span>
                  <span class="font-medium">{{ app.display_name }}</span>
                  <span class="text-slate-400 ml-auto">{{ app.category }}</span>
                </button>
              </div>
              <div v-if="form.individualApps.length" class="flex flex-wrap gap-1.5 mt-2">
                <span v-for="key in form.individualApps" :key="key"
                  class="flex items-center gap-1 text-xs bg-sky-50 border border-sky-200 text-sky-700 rounded-full px-2 py-0.5">
                  {{ appDisplayName(key) }}
                  <button @click="form.individualApps.splice(form.individualApps.indexOf(key),1)" class="hover:text-red-500">✕</button>
                </span>
              </div>
            </div>
          </template>

          <!-- Stage 5: Secrets -->
          <template v-if="currentStage === 5">
            <p class="text-xs text-slate-500 mb-2">Based on your selections, these secrets are required. Auto-generated values are pre-filled — review and change if needed. External credentials must be obtained from the links provided.</p>
            <div v-if="requiredSecrets.length === 0" class="text-sm text-green-600 bg-green-50 rounded-lg p-3">
              ✓ No external credentials required for your selections.
            </div>
            <div v-else class="space-y-3">
              <div v-for="secret in requiredSecrets" :key="secret.key" class="space-y-1">
                <div class="flex items-center justify-between">
                  <label class="label text-xs">
                    {{ secret.label }}
                    <span v-if="secret.required" class="text-red-400">*</span>
                    <span v-else class="text-slate-400 font-normal">(optional)</span>
                  </label>
                  <a v-if="secret.link" :href="secret.link" target="_blank" rel="noopener"
                    class="text-xs text-sky-600 underline hover:text-sky-700">
                    Get credentials ↗
                  </a>
                </div>
                <div class="flex gap-2">
                  <select v-if="secret.type === 'select'"
                    v-model="form.secrets[secret.key]"
                    class="input text-xs flex-1">
                    <option v-for="opt in secret.options" :key="opt" :value="opt">{{ opt }}</option>
                  </select>
                  <input v-else v-model="form.secrets[secret.key]"
                    :type="secret.type || (secretVisible[secret.key] ? 'text' : 'password')"
                    :placeholder="secret.placeholder || ''"
                    class="input font-mono text-xs flex-1" />
                  <button v-if="secret.type !== 'text' && secret.type !== 'select'"
                    @click="secretVisible[secret.key] = !secretVisible[secret.key]"
                    class="btn-secondary btn-sm text-xs shrink-0">
                    {{ secretVisible[secret.key] ? 'Hide' : 'Show' }}
                  </button>
                  <button v-if="secret.auto_generated"
                    @click="regenerateSecret(secret.key)"
                    class="btn-secondary btn-sm text-xs shrink-0" title="Generate a new random value">↺ New</button>
                </div>
                <p v-if="secret.note" class="text-xs text-slate-400">{{ secret.note }}</p>
              </div>
            </div>

            <!-- Secrets validation feedback -->
            <div v-if="secretsValidating" class="flex items-center gap-2 text-sm text-slate-500 mt-3">
              <div class="w-4 h-4 border-2 border-sky-400 border-t-transparent rounded-full animate-spin shrink-0"/>
              Validating credentials…
            </div>
            <div v-if="secretsValidationResult && secretsValidationResult.errors && secretsValidationResult.errors.length"
              class="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 space-y-1">
              <p class="text-xs font-medium text-red-800">Validation failed — fix these errors before continuing:</p>
              <ul class="text-xs text-red-700 list-disc list-inside space-y-0.5">
                <li v-for="err in secretsValidationResult.errors" :key="err">{{ err }}</li>
              </ul>
            </div>
            <div v-if="secretsValidationResult && secretsValidationResult.warnings && secretsValidationResult.warnings.length
              && !(secretsValidationResult.errors && secretsValidationResult.errors.length)"
              class="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <ul class="text-xs text-amber-700 list-disc list-inside space-y-0.5">
                <li v-for="warn in secretsValidationResult.warnings" :key="warn">{{ warn }}</li>
              </ul>
            </div>
          </template>

          <!-- Stage 6: Review -->
          <template v-if="currentStage === 6">
            <div class="space-y-3">
              <div class="rounded-lg bg-slate-50 border border-slate-200 p-4 space-y-2 text-sm">
                <div class="font-medium text-slate-700 mb-2">Deployment summary</div>
                <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <span class="text-slate-500">Domain</span><span class="font-mono">{{ form.domain }}</span>
                  <span class="text-slate-500">Config root</span><span class="font-mono">{{ form.config_root }}</span>
                  <span class="text-slate-500">DNS provider</span><span>{{ DNS_PROVIDERS[form.dns_provider]?.label }}</span>
                  <span class="text-slate-500">Cert authority</span><span>{{ form.cert_resolver }}</span>
                  <span class="text-slate-500">Infra</span>
                  <span>{{ Object.entries(form.infra).filter(([,v]) => v && v !== 'none').map(([k,v]) => v).join(', ') || 'Traefik only' }}</span>
                  <span class="text-slate-500">Quick stacks</span>
                  <span>{{ form.selectedStacks.length ? form.selectedStacks.map(id => QUICK_STACKS_CONFIG.find(s => s.id === id)?.label ?? id).join(', ') : 'None selected' }}</span>
                  <span class="text-slate-500">Notifications</span>
                  <span>{{ form.ntfy_enabled ? 'ntfy on ' + (form.ntfy_url || 'http://ntfy:80') + ' → ' + form.ntfy_topic : 'Will enable after installing ntfy from Catalog' }}</span>
                </div>
              </div>
              <div class="text-xs text-slate-400 rounded-lg bg-amber-50 border border-amber-100 p-3">
                ⚠ This will deploy Traefik and the selected infra apps. Existing installed apps are not affected.
              </div>
            </div>
          </template>

          <!-- Stage 7: Platform Deploy -->
          <template v-if="currentStage === 7">
            <div class="space-y-2">
              <div v-for="step in stepResults" :key="step.step"
                class="flex items-start gap-3">
                <div :class="['w-5 h-5 rounded-full flex items-center justify-center text-xs mt-0.5 shrink-0',
                  step.status === 'ok' ? 'bg-green-100 text-green-600' :
                  step.status === 'skipped' ? 'bg-slate-100 text-slate-400' :
                  'bg-red-100 text-red-600']">
                  {{ step.status === 'ok' ? '✓' : step.status === 'skipped' ? '−' : '✗' }}
                </div>
                <div class="flex-1 min-w-0">
                  <div :class="['text-sm font-medium',
                    step.status === 'error' ? 'text-red-700' :
                    step.status === 'skipped' ? 'text-slate-400' : 'text-slate-700']">
                    {{ step.message }}
                  </div>
                  <div v-if="step.detail" class="text-xs text-slate-400 mt-0.5 font-mono break-all">
                    {{ step.detail }}
                  </div>
                </div>
              </div>
              <div v-if="running" class="flex items-center gap-2 text-sm text-slate-400">
                <div class="w-4 h-4 border-2 border-sky-400 border-t-transparent rounded-full animate-spin"/>
                Deploying platform…
              </div>
            </div>
            <div v-if="setupError" class="rounded-xl border border-red-200 bg-red-50 p-4">
              <p class="text-sm font-medium text-red-800">Deployment failed</p>
              <p class="text-sm text-red-700 mt-1">{{ setupError }}</p>
              <button @click="runWizard" :disabled="running" class="btn-primary btn-sm mt-3">↺ Retry</button>
            </div>
            <div v-if="setupSuccess" class="rounded-xl border border-green-200 bg-green-50 p-4">
              <p class="text-green-800 font-medium text-center mb-2">✅ Platform deployed!</p>
              <div class="space-y-1">
                <div class="flex items-center gap-2 text-xs text-green-700">
                  <span>✓</span><span>Traefik running — reverse proxy ready</span>
                </div>
                <!-- DNS/cert status -->
                <div v-if="certStatus?.cert_found"
                  class="flex items-center gap-2 text-xs text-green-700 bg-green-100 rounded px-2 py-1.5 mt-1">
                  <span>🔒</span><span>{{ certStatus.message }}</span>
                </div>
                <div v-else class="flex items-center gap-2 text-xs text-sky-700 bg-sky-50 rounded px-2 py-1.5 mt-1">
                  <span v-if="!certStatus" class="w-3 h-3 border border-sky-400 border-t-transparent rounded-full animate-spin shrink-0"/>
                  <span>🔒</span>
                  <span v-if="certStatus">{{ certStatus.message }}</span>
                  <span v-else>Checking certificate status…</span>
                </div>
                <div v-if="form.tunnels.length > 0" class="flex items-center gap-2 text-xs text-green-700">
                  <span>✓</span><span>Tunnel: {{ form.tunnels.join(", ") }}</span>
                </div>
                <div v-if="form.infra.auth && form.infra.auth !== 'none'" class="flex items-center gap-2 text-xs text-amber-700 bg-amber-50 rounded px-2 py-1">
                  <span>⚠</span>
                  <span>{{ form.infra.auth === 'tinyauth' ? 'TinyAuth' : 'Authelia' }} is protecting your apps.
                  If Chrome prompts for a username/password, check the generated password in Secrets or disable auth temporarily.</span>
                </div>
                <div v-if="form.infra.dashboard && form.infra.dashboard !== 'none'" class="flex items-center gap-2 text-xs text-green-700">
                  <span>✓</span><span>Dashboard: {{ form.infra.dashboard }}</span>
                </div>
              </div>
            </div>
          </template>

          <!-- Stage 8: App Deploy -->
          <template v-if="currentStage === 8">
            <div v-if="form.selectedStacks.length === 0 && form.individualApps.length === 0"
              class="text-center py-8 text-slate-400">
              <div class="text-2xl mb-2">📦</div>
              <div class="text-sm font-medium">No apps selected</div>
              <div class="text-xs mt-1">You can install apps anytime from the Catalog.</div>
            </div>
            <div v-else class="space-y-3">
              <!-- Progress header -->
              <div v-if="installStarted" class="flex items-center justify-between">
                <div class="text-xs font-medium text-slate-600">
                  {{ stackAppsToInstall.filter(k => appInstallStatus[k] === 'ok').length }}
                  / {{ stackAppsToInstall.length }} installed
                </div>
                <div v-if="!stackInstallDone" class="flex items-center gap-1.5 text-xs text-sky-500">
                  <span class="w-3 h-3 border-2 border-sky-400 border-t-transparent rounded-full animate-spin"/>
                  Installing…
                </div>
                <div v-else-if="stackAppsToInstall.every(k => appInstallStatus[k] === 'ok')"
                  class="text-xs text-green-500 font-medium">✓ All installed</div>
              </div>

              <!-- App cards grid -->
              <div class="grid gap-2">
                <div v-for="app in stackAppsToInstall" :key="app"
                  :class="['rounded-lg border px-3 py-2.5 flex items-center gap-3 transition-colors',
                    appInstallStatus[app] === 'ok'      ? 'border-green-200 bg-green-50' :
                    appInstallStatus[app] === 'error'   ? 'border-red-200 bg-red-50' :
                    appInstallStatus[app] === 'running' ? 'border-sky-200 bg-sky-50' :
                    'border-slate-100 bg-white']">
                  <!-- Icon -->
                  <div class="text-xl shrink-0 w-8 text-center">{{ appIcon(app) }}</div>
                  <!-- Name + status -->
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-slate-700">{{ appDisplayName(app) }}</span>
                      <!-- Status badge -->
                      <span v-if="appInstallStatus[app] === 'ok'"
                        class="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">Installed</span>
                      <span v-else-if="appInstallStatus[app] === 'error'"
                        class="text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">Failed</span>
                      <span v-else-if="appInstallStatus[app] === 'running'"
                        class="text-xs bg-sky-100 text-sky-600 px-1.5 py-0.5 rounded-full flex items-center gap-1">
                        <span class="w-2 h-2 border border-sky-400 border-t-transparent rounded-full animate-spin"/>
                        Installing
                      </span>
                      <span v-else-if="appInstallStatus[app] === 'queued'"
                        class="text-xs text-slate-400">Queued</span>
                    </div>
                    <!-- Progress message or error -->
                    <div v-if="appInstallStatus[app] === 'running' && appInstallProgress[app]"
                      class="text-xs text-sky-500 mt-0.5">{{ appInstallProgress[app] }}</div>
                    <div v-if="appInstallStatus[app] === 'error' && appInstallError[app]"
                      class="text-xs text-red-500 mt-0.5 break-all">{{ appInstallError[app] }}</div>
                  </div>
                  <!-- Status icon -->
                  <div class="shrink-0 text-base">
                    <span v-if="appInstallStatus[app] === 'ok'" class="text-green-500">✓</span>
                    <span v-else-if="appInstallStatus[app] === 'error'" class="text-red-400">✗</span>
                    <span v-else-if="appInstallStatus[app] === 'running'"
                      class="block w-4 h-4 border-2 border-sky-400 border-t-transparent rounded-full animate-spin"/>
                    <span v-else class="text-slate-200">○</span>
                  </div>
                </div>
              </div>

              <!-- Footer actions -->
              <div v-if="stackInstallDone && stackAppsToInstall.some(k => appInstallStatus[k] === 'error')"
                class="flex items-center justify-between pt-2 border-t border-slate-100">
                <p class="text-xs text-slate-400">Failed apps can be installed from Catalog after setup.</p>
                <button @click="retryFailedApps" class="btn-secondary btn-sm text-xs">↺ Retry failed</button>
              </div>
            </div>
          </template>

          <!-- Stage 9: AI / LLM -->
          <template v-if="currentStage === 9">
            <p class="text-xs text-slate-500">The AI agent diagnoses app failures, suggests fixes, and auto-heals common issues.</p>
            <div class="space-y-3">

              <!-- Local Ollama -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'ollama' ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'ollama'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="ollama" type="radio" class="w-4 h-4 shrink-0"/>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium">Local AI (Ollama) — Recommended</div>
                    <div class="text-xs text-slate-400 mt-0.5">
                      Runs on your server. Private. No API key. ~3GB download.
                    </div>
                  </div>
                  <span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full shrink-0">Private</span>
                </div>

                <!-- Model selector + auto-install progress when Ollama selected -->
                <div v-if="form.llm_provider === 'ollama'" class="mt-3 ml-7 space-y-2">
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-14 shrink-0">Server:</label>
                    <select v-model="form.ollama_server" class="input text-xs w-52 shrink-0">
                      <option value="local">This server (install now)</option>
                      <option value="remote">Remote Ollama server</option>
                    </select>
                    <input v-if="form.ollama_server === 'remote'"
                      v-model="form.ollama_url"
                      type="text" placeholder="http://192.168.1.x:11434"
                      class="input text-xs flex-1 font-mono" />
                  </div>
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-14 shrink-0">Model:</label>
                    <select v-model="form.ollama_model" class="input text-xs flex-1">
                      <option v-for="m in ollamaModelOptions" :key="m.value" :value="m.value">
                        {{ m.label }}
                      </option>
                    </select>
                  </div>
                  <div class="text-xs text-slate-400">
                    <span v-if="form.ollama_server === 'local'">Ollama will be installed on this server and the model downloaded during setup.</span>
                    <span v-else>Model will be pulled on your remote Ollama server.</span>
                  </div>

                  <!-- Install + pull progress -->
                  <div v-if="ollamaSetupJob" class="rounded-lg bg-white border border-slate-100 p-3 space-y-2">
                    <!-- Phase indicator -->
                    <div class="flex items-center gap-2 text-xs">
                      <span v-if="!ollamaSetupJob.done"
                        class="w-3 h-3 border border-sky-400 border-t-transparent rounded-full animate-spin shrink-0"/>
                      <span v-else-if="ollamaSetupJob.ok" class="text-green-500 shrink-0">✓</span>
                      <span v-else class="text-red-500 shrink-0">✗</span>
                      <span :class="ollamaSetupJob.ok ? 'text-green-700' : ollamaSetupJob.phase === 'error' ? 'text-red-600' : 'text-slate-600'">
                        {{ ollamaSetupJob.message }}
                      </span>
                    </div>
                    <!-- Progress bar -->
                    <div v-if="!ollamaSetupJob.done || ollamaSetupJob.ok" class="w-full bg-slate-100 rounded-full h-1.5">
                      <div class="bg-sky-500 h-1.5 rounded-full transition-all duration-500"
                        :style="{ width: ollamaSetupJob.progress + '%' }"/>
                    </div>
                    <!-- Retry on error -->
                    <button v-if="ollamaSetupJob.phase === 'error'"
                      @click="startOllamaSetup"
                      class="btn-secondary btn-sm text-xs">↺ Retry</button>
                  </div>

                  <!-- Start button (before job begins) -->
                  <button v-if="!ollamaSetupJob && !ollamaSetupJobId"
                    @click="startOllamaSetup"
                    class="btn-primary btn-sm text-xs">
                    ▶ Install Ollama + download {{ form.ollama_model }}
                  </button>
                  <div v-if="ollamaSetupJob?.ok" class="flex items-center gap-1.5 text-xs text-green-600">
                    <span>✓</span><span>Ready — AI agent will activate after first health cycle</span>
                  </div>
                </div>
              </div>

              <!-- Local: llama.cpp -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'llamacpp' ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'llamacpp'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="llamacpp" type="radio" class="w-4 h-4 shrink-0"/>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium">llama.cpp (local, OpenAI-compatible)</div>
                    <div class="text-xs text-slate-400">Lightweight CPU inference. Point to any llama.cpp server on your network.</div>
                  </div>
                  <span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full shrink-0">CPU · No GPU</span>
                </div>
                <div v-if="form.llm_provider === 'llamacpp'" class="mt-3 ml-7 space-y-2">
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-20 shrink-0">Server URL:</label>
                    <input v-model="form.llamacpp_url" type="text"
                      placeholder="http://localhost:8081" class="input text-xs flex-1 font-mono" />
                  </div>
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-20 shrink-0">Model name:</label>
                    <input v-model="form.llamacpp_model" type="text"
                      placeholder="phi-4-mini (or any model tag)" class="input text-xs flex-1 font-mono" />
                  </div>
                  <p class="text-xs text-slate-400">
                    Runs any GGUF model. Start with:
                    <code class="bg-slate-100 px-1 rounded">docker run -p 8081:8080 ghcr.io/ggerganov/llama.cpp:server -m your-model.gguf</code>
                  </p>
                </div>
              </div>

              <!-- Cloud: Groq -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'groq' ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'groq'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="groq" type="radio" class="w-4 h-4"/>
                  <div>
                    <div class="text-sm font-medium">Cloud AI (Groq)</div>
                    <div class="text-xs text-slate-400">Free tier. Instant. Requires a free API key at console.groq.com.</div>
                  </div>
                  <span class="text-xs bg-sky-100 text-sky-700 px-2 py-0.5 rounded-full shrink-0">No GPU</span>
                </div>
                <div v-if="form.llm_provider === 'groq'" class="mt-3 ml-7 space-y-2">
                  <a href="https://console.groq.com/keys" target="_blank" rel="noopener"
                    class="text-xs text-sky-600 underline">Get a free Groq API key ↗</a>
                  <input v-model="form.groq_api_key" type="password" class="input text-xs"
                    placeholder="gsk_…" />
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-14 shrink-0">Model:</label>
                    <select v-model="form.groq_model" class="input text-xs flex-1">
                      <option value="llama-3.3-70b-versatile">Llama 3.3 70B — best quality (recommended)</option>
                      <option value="llama-3.1-8b-instant">Llama 3.1 8B — fastest</option>
                      <option value="llama3-70b-8192">Llama 3 70B — balanced</option>
                      <option value="mixtral-8x7b-32768">Mixtral 8x7B — good reasoning</option>
                      <option value="gemma2-9b-it">Gemma 2 9B — efficient</option>
                    </select>
                  </div>
                </div>
              </div>

              <!-- Cloud: Awan LLM -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'awan' ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'awan'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="awan" type="radio" class="w-4 h-4"/>
                  <div>
                    <div class="text-sm font-medium">Cloud AI (Awan LLM)</div>
                    <div class="text-xs text-slate-400">Free tier. OpenAI-compatible. Get a key at awanllm.com.</div>
                  </div>
                  <span class="text-xs bg-sky-100 text-sky-700 px-2 py-0.5 rounded-full shrink-0">No GPU</span>
                </div>
                <div v-if="form.llm_provider === 'awan'" class="mt-3 ml-7 space-y-2">
                  <a href="https://www.awanllm.com/" target="_blank" rel="noopener"
                    class="text-xs text-sky-600 underline">Get a free Awan LLM API key ↗</a>
                  <input v-model="form.awan_api_key" type="password" class="input text-xs"
                    placeholder="Awan API key…" />
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-14 shrink-0">Model:</label>
                    <select v-model="form.awan_model" class="input text-xs flex-1">
                      <option value="Meta-Llama-3.1-8B-Instruct">Llama 3.1 8B — fast, free (recommended)</option>
                      <option value="Meta-Llama-3.1-70B-Instruct">Llama 3.1 70B — best quality</option>
                      <option value="Mistral-7B-Instruct-v0.3">Mistral 7B — efficient</option>
                      <option value="Qwen2.5-7B-Instruct">Qwen 2.5 7B — strong reasoning</option>
                    </select>
                  </div>
                </div>
              </div>


              <!-- Cloud: Cerebras -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'cerebras' ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'cerebras'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="cerebras" type="radio" class="w-4 h-4"/>
                  <div>
                    <div class="text-sm font-medium">Cloud AI (Cerebras)</div>
                    <div class="text-xs text-slate-400">Free tier. World's fastest inference. console.cerebras.ai</div>
                  </div>
                  <span class="text-xs bg-sky-100 text-sky-700 px-2 py-0.5 rounded-full shrink-0">No GPU</span>
                </div>
                <div v-if="form.llm_provider === 'cerebras'" class="mt-3 ml-7 space-y-2">
                  <a href="https://console.cerebras.ai/tokens" target="_blank" rel="noopener"
                    class="text-xs text-sky-600 underline">Get a free Cerebras API key ↗</a>
                  <input v-model="form.cerebras_api_key" type="password" class="input text-xs"
                    placeholder="csk-…" />
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-14 shrink-0">Model:</label>
                    <select v-model="form.cerebras_model" class="input text-xs flex-1">
                      <option value="llama-3.3-70b">Llama 3.3 70B — best quality (recommended)</option>
                      <option value="llama3.1-8b">Llama 3.1 8B — fastest</option>
                      <option value="qwen-3-32b">Qwen 3 32B — strong reasoning</option>
                    </select>
                  </div>
                </div>
              </div>

              <!-- Cloud: OpenAI -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'openai' ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'openai'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="openai" type="radio" class="w-4 h-4"/>
                  <div>
                    <div class="text-sm font-medium">Cloud AI (OpenAI)</div>
                    <div class="text-xs text-slate-400">Paid. GPT-4o and o3-mini. platform.openai.com</div>
                  </div>
                  <span class="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full shrink-0">Paid</span>
                </div>
                <div v-if="form.llm_provider === 'openai'" class="mt-3 ml-7 space-y-2">
                  <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener"
                    class="text-xs text-sky-600 underline">Get an OpenAI API key ↗</a>
                  <input v-model="form.openai_api_key" type="password" class="input text-xs"
                    placeholder="sk-…" />
                  <div class="flex items-center gap-2">
                    <label class="text-xs text-slate-500 w-14 shrink-0">Model:</label>
                    <select v-model="form.openai_model" class="input text-xs flex-1">
                      <option value="gpt-4o-mini">GPT-4o mini — fast, affordable (recommended)</option>
                      <option value="gpt-4o">GPT-4o — best quality</option>
                      <option value="o3-mini">o3-mini — strong reasoning</option>
                    </select>
                  </div>
                </div>
              </div>

              <!-- Skip -->
              <div :class="['border rounded-lg p-3 cursor-pointer transition-colors',
                form.llm_provider === 'none' ? 'border-slate-400 bg-slate-50' : 'border-slate-200 hover:border-slate-300']"
                @click="form.llm_provider = 'none'">
                <div class="flex items-center gap-3">
                  <input v-model="form.llm_provider" value="none" type="radio" class="w-4 h-4"/>
                  <div>
                    <div class="text-sm font-medium text-slate-500">Skip for now</div>
                    <div class="text-xs text-slate-400">Enable later in Settings → AI.</div>
                  </div>
                </div>
              </div>

            </div>
          </template>

          <!-- Stage 10: Storage -->
          <template v-if="currentStage === 10">
            <p class="text-xs text-slate-500">Configure shared storage sources. Media files will be accessible to all arr apps and media servers.</p>
            <div class="space-y-3">
              <div class="border border-slate-200 rounded-lg p-3">
                <div class="text-sm font-medium mb-2">Media directory</div>
                <input v-model="form.media_root" type="text" class="input text-xs" />
                <p class="text-xs text-slate-400 mt-1">Local path to your media files. All apps will mount this as /media.</p>
              </div>
              <div class="border border-slate-200 rounded-lg p-3">
                <div class="flex items-center justify-between mb-2">
                  <div class="text-sm font-medium">NFS mount</div>
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input v-model="form.nfs_enabled" type="checkbox" class="w-3.5 h-3.5"/>
                    <span class="text-xs">Enable</span>
                  </label>
                </div>
                <div v-if="form.nfs_enabled" class="grid grid-cols-2 gap-2">
                  <input v-model="form.nfs_server" type="text" class="input text-xs" placeholder="192.168.1.10" />
                  <input v-model="form.nfs_export" type="text" class="input text-xs" placeholder="/exports/media" />
                </div>
              </div>
              <p class="text-xs text-slate-400">NFS settings will be saved when you click Finish. rclone and other sources can be added later via the Storage page.</p>
            </div>
          </template>

        </div>
      </div>

      <!-- Navigation buttons -->
      <div class="flex gap-3">
        <button v-if="currentStage > 0" @click="prevStage" class="btn-secondary">← Back</button>
        <div class="flex-1"/>
        <button v-if="currentStage < STAGES.length - 1" @click="nextStage"
          :disabled="!canAdvance" class="btn-primary">
          {{ currentStage === 6 ? 'Deploy Platform →' : 'Continue →' }}
        </button>
        <button v-if="currentStage === STAGES.length - 1" @click="finish" :disabled="finishing" class="btn-primary">
          {{ finishing ? "Finishing…" : "Finish Setup →" }}
        </button>
      </div>

      <!-- Skip to catalog link -->
      <p v-if="currentStage === 9 && form.llm_provider === 'ollama' && !ollamaSetupJob?.ok"
        class="text-center text-xs text-slate-400 mt-2">
        <button @click="form.llm_provider = 'none'" class="text-sky-500 hover:underline">
          Skip AI monitoring — set up Ollama later
        </button>
      </p>
      <p v-if="currentStage < 6" class="text-center text-xs text-slate-400 mt-3">
        <RouterLink to="/catalog" class="underline hover:text-slate-600">Skip to Catalog — configure later</RouterLink>
      </p>
    </template>

    <!-- Reset confirmation modal -->
    <Teleport to="body">
      <div v-if="showReset" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="showReset = false"/>
        <div class="relative card w-full max-w-md mx-4 card-body">
          <h3 class="font-semibold text-slate-900">Reset platform</h3>
          <p class="text-sm text-slate-500 mt-2 mb-4">Choose how much to reset:</p>
          <div class="space-y-3">
            <div class="rounded-lg border border-slate-200 p-3">
              <div class="font-medium text-sm text-slate-800 mb-1">↺ Re-run wizard</div>
              <p class="text-xs text-slate-500">Resets platform status so you can reconfigure. Clears infra slots, Traefik fragment, health data. <strong>Installed apps keep running.</strong></p>
              <button @click="doReset" class="btn-secondary btn-sm mt-2 w-full">Re-run wizard</button>
            </div>
            <div class="rounded-lg border border-red-200 bg-red-50 p-3">
              <div class="font-medium text-sm text-red-800 mb-1">⚠ Full factory reset</div>
              <p class="text-xs text-red-700">Stops ALL containers, removes all compose fragments, wipes entire DB, clears .env. Irreversible — use only if starting completely fresh.</p>
              <button @click="doFullReset" class="btn-danger btn-sm mt-2 w-full">Full factory reset</button>
            </div>
          </div>
          <button @click="showReset = false" class="btn-secondary w-full mt-3">Cancel</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { RouterLink, useRouter, useRoute } from 'vue-router'
import { usePlatformStore } from '../stores/platform'
import { platform as platformApi } from '../api/client'

const platformStore = usePlatformStore()
const router = useRouter()
const route = useRoute()

// Allow forcing wizard open even when platform is ready (from Settings re-run)
const forceSetup = ref(route.query.force === 'true')

// ── DNS Provider metadata ─────────────────────────────────────────────────
const DNS_PROVIDERS: Record<string, { label: string; vars: string[]; link: string }> = {
  cloudflare:   { label: "Cloudflare",       vars: ["CF_DNS_API_TOKEN"],                                                      link: "https://dash.cloudflare.com/profile/api-tokens" },
  route53:      { label: "AWS Route 53",      vars: ["AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","AWS_REGION","AWS_HOSTED_ZONE_ID"], link: "https://console.aws.amazon.com/iam/" },
  namecheap:    { label: "Namecheap",         vars: ["NAMECHEAP_API_USER","NAMECHEAP_API_KEY"],                                link: "https://ap.www.namecheap.com/settings/tools/apiaccess/" },
  porkbun:      { label: "Porkbun",           vars: ["PORKBUN_API_KEY","PORKBUN_SECRET_API_KEY"],                              link: "https://porkbun.com/account/api" },
  digitalocean: { label: "DigitalOcean",      vars: ["DO_AUTH_TOKEN"],                                                        link: "https://cloud.digitalocean.com/account/api/tokens" },
  gandi:        { label: "Gandi",             vars: ["GANDI_PERSONAL_ACCESS_TOKEN"],                                          link: "https://account.gandi.net/en/users/_/security" },
  hetzner:      { label: "Hetzner",           vars: ["HETZNER_API_KEY"],                                                      link: "https://dns.hetzner.com/settings/api-token" },
  linode:       { label: "Linode / Akamai",   vars: ["LINODE_TOKEN"],                                                         link: "https://cloud.linode.com/profile/tokens" },
  ovh:          { label: "OVH",               vars: ["OVH_ENDPOINT","OVH_APPLICATION_KEY","OVH_APPLICATION_SECRET","OVH_CONSUMER_KEY"], link: "https://api.ovh.com/createToken/" },
  godaddy:      { label: "GoDaddy",           vars: ["GODADDY_API_KEY","GODADDY_API_SECRET"],                                  link: "https://developer.godaddy.com/keys" },
  duckdns:      { label: "DuckDNS",           vars: ["DUCKDNS_TOKEN"],                                                        link: "https://www.duckdns.org/" },
  desec:        { label: "deSEC",             vars: ["DESEC_TOKEN"],                                                          link: "https://desec.io/tokens" },
  njalla:       { label: "Njalla",            vars: ["NJALLA_TOKEN"],                                                         link: "https://njal.la/settings/api/" },
  inwx:         { label: "INWX",              vars: ["INWX_USERNAME","INWX_PASSWORD"],                                        link: "https://www.inwx.com/en/offer/api" },
  infomaniak:   { label: "Infomaniak",        vars: ["INFOMANIAK_ACCESS_TOKEN"],                                              link: "https://manager.infomaniak.com/v3/profile/api-tokens" },
  azure:        { label: "Azure DNS",         vars: ["AZURE_CLIENT_ID","AZURE_CLIENT_SECRET","AZURE_SUBSCRIPTION_ID","AZURE_RESOURCE_GROUP"], link: "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps" },
  google:       { label: "Google Cloud DNS",  vars: ["GCE_PROJECT","GCE_SERVICE_ACCOUNT_FILE"],                               link: "https://console.cloud.google.com/iam-admin/serviceaccounts" },
  vultr:        { label: "Vultr",             vars: ["VULTR_API_KEY"],                                                        link: "https://my.vultr.com/settings/#settingsapi" },
  bunny:        { label: "Bunny DNS",         vars: ["BUNNY_API_KEY"],                                                        link: "https://panel.bunny.net/account" },
  dnspod:       { label: "DNSPod",            vars: ["DNSPOD_API_KEY","DNSPOD_SECRET_ID"],                                    link: "https://console.dnspod.cn/account/token/apikey" },
}

// ── Stage definitions ─────────────────────────────────────────────────────
const STAGES = [
  { id: 'prereqs',    label: 'Prerequisites', description: 'Verify Docker and system requirements' },
  { id: 'core',       label: 'Core Config',   description: 'Domain, paths, and system settings' },
  { id: 'tls',        label: 'TLS / DNS',     description: 'Certificate authority and DNS provider' },
  { id: 'infra',      label: 'Infrastructure',description: 'Auth, tunnel, VPN, and dashboard apps' },
  { id: 'stacks',     label: 'Quick Stacks',  description: 'Optional: select app bundles to pre-install' },
  { id: 'secrets',    label: 'Secrets',       description: 'Credentials required by your selections' },
  { id: 'review',     label: 'Review',        description: 'Confirm your configuration before deploying' },
  { id: 'deploy',     label: 'Deploy',        description: 'Deploy Traefik and infrastructure' },
  { id: 'apps',       label: 'Apps',          description: 'Install selected quick stacks' },
  { id: 'ai',         label: 'AI Monitoring', description: 'Optional: configure the health AI agent' },
  { id: 'storage',    label: 'Storage',       description: 'Optional: configure shared storage' },
]

// Tunnel supports multi-select (you can run cloudflared + tailscale simultaneously)
const INFRA_SLOTS = [
  { slot: 'auth', label: 'Authentication', description: 'Protect apps with a login page', multi: false,
    options: [{ value: 'none', label: 'None' }, { value: 'tinyauth', label: 'TinyAuth (simple)' }, { value: 'authelia', label: 'Authelia (full SSO)' }] },
  { slot: 'tunnel', label: 'External Access Tunnel', description: 'Expose apps without port forwarding. Select all that apply.', multi: true,
    options: [{ value: 'cloudflared', label: 'Cloudflare Tunnel' }, { value: 'tailscale', label: 'Tailscale' }, { value: 'headscale', label: 'Headscale (self-hosted)' }] },
  { slot: 'vpn', label: 'VPN (for download clients)', description: 'Route torrent/usenet traffic through VPN', multi: false,
    options: [{ value: 'none', label: 'None' }, { value: 'gluetun', label: 'Gluetun' }] },
  { slot: 'dashboard', label: 'Dashboard', description: 'Homepage for your homelab', multi: false,
    options: [{ value: 'none', label: 'None' }, { value: 'glance', label: 'Glance' }, { value: 'homepage', label: 'Homepage' }] },
  { slot: 'management', label: 'Container Management', description: 'GUI to manage Docker stacks', multi: false,
    options: [{ value: 'none', label: 'None' }, { value: 'dockge', label: 'Dockge' }, { value: 'portainer', label: 'Portainer' }, { value: 'dockhand', label: 'Dockhand' }, { value: 'komodo', label: 'Komodo' }] },
]

// RAM needed per stack in GB for warning thresholds
const STACK_MIN_RAM: Record<string, number> = {
  arr_basic: 2, debrid: 1, media_server: 4, immich: 8, monitoring: 1, productivity: 2,
}
const QUICK_STACKS_CONFIG = [
  { id: 'arr_basic', label: 'Arr Stack', apps: ['Sonarr', 'Radarr', 'Prowlarr', 'SABnzbd'], ram_note: '~2GB RAM' },
  { id: 'debrid', label: 'Debrid Stack', apps: ['Decypharr', 'Zilean', 'DUMB'], ram_note: '~1GB RAM · Real-Debrid / TorBox / AllDebrid' },
  { id: 'media_server', label: 'Jellyfin Media Server', apps: ['Jellyfin', 'Jellyseerr'], ram_note: '~4GB RAM' },
  { id: 'immich', label: 'Photo Management (Immich)', apps: ['Immich', 'PostgreSQL', 'Redis'], ram_note: '~8GB RAM' },
  { id: 'monitoring', label: 'Monitoring Stack', apps: ['Dozzle', 'Beszel', 'Scrutiny'], ram_note: '~1GB RAM' },
  { id: 'productivity', label: 'Productivity', apps: ['Vaultwarden', 'Paperless-ngx', 'Mealie'], ram_note: '~2GB RAM' },
]

// ── Form state ─────────────────────────────────────────────────────────────
const form = reactive({
  domain: '',
  config_root: '/var/lib/mediastack/config',
  media_root: '/mnt/media',
  puid: 1000,
  pgid: 1000,
  timezone: 'America/Los_Angeles',
  cert_resolver: 'letsencrypt',
  network_name: 'mediastack',
  acme_email: '',
  dns_provider: 'cloudflare',
  eab_kid: '',
  eab_hmac: '',
  ntfy_url: 'http://ntfy:80',
  ntfy_topic: 'mediastack',
  ntfy_enabled: true,  // pre-enable since http://ntfy:80 is the correct default
  infra: { auth: 'none', vpn: 'none', dashboard: 'none', management: 'none' } as Record<string, string>,
  tunnels: [] as string[],  // multi-select: can have cloudflared + tailscale simultaneously
  selectedStacks: [] as string[],
  secrets: {} as Record<string, string>,
  llm_provider: 'none',
  groq_api_key: '',
  groq_model: 'llama-3.3-70b-versatile',
  awan_model: 'Meta-Llama-3.1-8B-Instruct',
  cerebras_api_key: '',
  cerebras_model: 'llama-3.3-70b',
  openai_api_key: '',
  openai_model: 'gpt-4o-mini',
  llamacpp_url: 'http://localhost:8081',
  llamacpp_model: 'phi-4-mini',
  awan_api_key: '',
  ollama_model: 'phi4-mini',
  ollama_server: 'local',
  ollama_url: 'http://ollama:11434',
  nfs_enabled: false,
  nfs_server: '',
  nfs_export: '',
  individualApps: [] as string[],
})

// ── Stage navigation ───────────────────────────────────────────────────────
const currentStage = ref(0)
const maxReachedStage = ref(0)

function goToStage(i: number) {
  if (i <= maxReachedStage.value) currentStage.value = i
}

function prevStage() {
  if (currentStage.value > 0) currentStage.value--
}

async function nextStage() {
  if (currentStage.value === 6) {
    // Stage 6 → 7: trigger wizard deployment
    currentStage.value = 7
    maxReachedStage.value = Math.max(maxReachedStage.value, 7)
    await runWizard()
    return
  }
  if (currentStage.value === 7) {
    // Stage 7 → 8: start app installs
    currentStage.value = 8
    maxReachedStage.value = Math.max(maxReachedStage.value, 8)
    if (form.selectedStacks.length > 0 || form.individualApps.length > 0) {
      await installStacks()
    } else {
      stackInstallDone.value = true
    }
    return
  }
  // Before leaving Stage 5 (Secrets): run validation checks
  if (currentStage.value === 5) {
    // Quick connectivity validation — check credentials work before committing to deploy
    const toValidate: string[] = []
    if (form.infra.vpn === 'gluetun') toValidate.push('vpn')
    if (form.tunnels.includes('cloudflared')) toValidate.push('cloudflared')
    if (form.tunnels.includes('tailscale')) toValidate.push('tailscale')
    if (form.dns_provider && form.dns_provider !== 'none') toValidate.push('dns')

    if (toValidate.length > 0) {
      secretsValidating.value = true
      secretsValidationResult.value = null
      try {
        const r = await fetch('/api/v1/platform/wizard/validate-secrets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            checks: toValidate,
            vpn_type: form.secrets['VPN_TYPE'],
            vpn_provider: form.secrets['VPN_SERVICE_PROVIDER'],
            vpn_key: form.secrets['WIREGUARD_PRIVATE_KEY'] || form.secrets['OPENVPN_USER'],
            cf_tunnel_token: form.secrets['CF_TUNNEL_TOKEN'],
            tailscale_key: form.secrets['TAILSCALE_AUTH_KEY'],
            cf_dns_token: form.secrets['CF_DNS_API_TOKEN'],
            dns_provider: form.dns_provider,
          }),
        })
        const result = r.ok ? await r.json() : { ok: false, warnings: ['Validation endpoint not reachable'] }
        secretsValidationResult.value = result
        // Block on hard failures, warn on soft failures
        if (result.errors?.length) {
          secretsValidating.value = false
          return  // stay on Stage 5 and show errors
        }
      } catch {
        secretsValidationResult.value = { ok: true, warnings: ['Could not validate — proceeding anyway'] }
      }
      secretsValidating.value = false
    }
  }

  if (currentStage.value === 5 && form.infra.auth === 'tinyauth') {
    const user = form.secrets['TINYAUTH_USERNAME']?.trim() || 'admin'
    const pass = form.secrets['TINYAUTH_PASSWORD']?.trim()
    if (pass) {
      try {
        const r = await fetch('/api/v1/platform/wizard/bcrypt-users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: user, password: pass }),
        })
        if (r.ok) {
          const d = await r.json()
          form.secrets['TINYAUTH_AUTH_USERS'] = d.users
          form.secrets['TINYAUTH_USERNAME'] = user
        }
      } catch {}
    }
  }
  currentStage.value++
  maxReachedStage.value = Math.max(maxReachedStage.value, currentStage.value)
}

const finishing = ref(false)
const wizardLLMProviders = ref<any>(null)

async function finish() {
  finishing.value = true
  await saveLLMConfig()
  // Save NFS storage if configured
  if (form.nfs_enabled && form.nfs_server && form.nfs_export) {
    try {
      await fetch('/api/v1/storage/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: 'NFS Media',
          type: 'nfs',
          host: form.nfs_server,
          path: form.nfs_export,
          mount_point: form.media_root,
          enabled: true,
        }),
      })
    } catch {}
  }
  await platformStore.fetchStatus()
  await new Promise(r => setTimeout(r, 500))
  router.push('/')
}

const canAdvance = computed(() => {
  if (currentStage.value === 0)
    return prereqChecks.value.length > 0 && !prereqChecks.value.some(c => c.status === 'error')
  if (currentStage.value === 1) return !!form.domain
  if (currentStage.value === 2)
    return form.cert_resolver !== 'zerossl' || (!!form.eab_kid && !!form.eab_hmac)
  if (currentStage.value === 5) {
    // All required, non-auto-generated secrets must be filled
    const missing = requiredSecrets.value.filter(
      s => s.required && !s.auto_generated && !form.secrets[s.key]?.trim()
    )
    return missing.length === 0
  }
  if (currentStage.value === 7) return setupSuccess.value
  if (currentStage.value === 8) return stackInstallDone.value
  if (currentStage.value === 9) {
    if (form.llm_provider === 'ollama') return ollamaSetupJob.value?.ok === true
    if (form.llm_provider === 'groq') return !!form.groq_api_key?.trim()
    if (form.llm_provider === 'awan') return !!form.awan_api_key?.trim()
    if (form.llm_provider === 'llamacpp') return !!form.llamacpp_url?.trim()
    if (form.llm_provider === 'cerebras') return !!form.cerebras_api_key?.trim()
    if (form.llm_provider === 'openai') return !!form.openai_api_key?.trim()
    return true  // 'none' — always can advance
  }
  return true
})

// ── Prerequisites ─────────────────────────────────────────────────────────
const prereqChecks = ref<{key:string; label:string; status:string; value?:string; detail?:string}[]>([])
const prereqRunning = ref(false)
const prereqError = ref('')

async function runPrereqChecks() {
  prereqRunning.value = true
  prereqError.value = ''
  try {
    const res = await fetch('/api/v1/platform/prereqs')
    const data = await res.json()
    prereqChecks.value = data.checks || []
    // Auto-fill Stage 1 values from real system data regardless of check pass/fail
    // (some checks may warn but values are still valid)
    const sys = data.system || {}
    if (sys.puid) form.puid = sys.puid
    if (sys.pgid) form.pgid = sys.pgid
    if (sys.timezone) form.timezone = sys.timezone
    if (sys.config_root) form.config_root = sys.config_root
    systemProfile.value = {
      ...(systemProfile.value || {}),
      server_ip: sys.server_ip,
      ram_gb: sys.ram_gb,
      recommended_model: sys.recommended_model,
      available_models: sys.available_models || [],
      llm_warning: sys.llm_warning,
      gpu_name: sys.gpu_name,
      gpu_vram_gb: sys.gpu_vram_gb,
      puid_username: sys.puid_username,
      ollama_running: sys.ollama_running || false,
      ollama_models: sys.ollama_models || [],
      ollama_recommended_loaded: sys.ollama_recommended_loaded || false,
    }
    // Auto-select recommended model
    if (sys.recommended_model) form.ollama_model = sys.recommended_model
  } catch (e) {
    prereqError.value = String(e)
  } finally {
    prereqRunning.value = false
  }
}

// ── System profile for LLM stage ─────────────────────────────────────────
const systemProfile = ref<any>(null)

// ── Secrets derivation ────────────────────────────────────────────────────
function hex(len = 32) {
  return Array.from(crypto.getRandomValues(new Uint8Array(len)))
    .map(b => b.toString(16).padStart(2, '0')).join('')
}

const requiredSecrets = computed(() => {
  const secrets: any[] = []

  // DNS provider credentials — driven from DNS_PROVIDERS map so all providers are covered
  const dnsInfo = DNS_PROVIDERS[form.dns_provider]
  if (dnsInfo) {
    for (const varKey of dnsInfo.vars) {
      secrets.push({
        key: varKey,
        label: `${dnsInfo.label}: ${varKey.replace(/_/g, ' ')}`,
        required: true,
        link: dnsInfo.link,
        placeholder: varKey.toLowerCase().includes('password') ? '••••••••' : `${varKey}…`,
        type: varKey.toLowerCase().includes('password') ? 'password' : 'text',
        note: secrets.length === 0 ? `Get credentials at ${dnsInfo.link}` : undefined,
      })
    }
  }
  // Tunnels are multi-select stored in form.tunnels (not form.infra.tunnel)
  if (form.tunnels.includes('cloudflared')) {
    secrets.push({ key: 'CF_TUNNEL_TOKEN', label: 'Cloudflare Tunnel Token', required: true,
      link: 'https://one.dash.cloudflare.com/', placeholder: 'eyJhbGci… (long base64 token)',
      note: 'one.dash.cloudflare.com → Networks → Tunnels → Create/select tunnel → Overview → copy the token string shown in the cloudflared install command.' })
  }
  if (form.tunnels.includes('tailscale')) {
    secrets.push({ key: 'TAILSCALE_AUTH_KEY', label: 'Tailscale Auth Key', required: true,
      link: 'https://login.tailscale.com/admin/authkeys', placeholder: 'tskey-auth-…' })
  }
  if (form.tunnels.includes('headscale')) {
    secrets.push({ key: 'HEADSCALE_AUTH_KEY', label: 'Headscale Pre-auth Key', required: true,
      link: 'https://headscale.net/docs/ref/preauthkeys/', placeholder: 'xxxx',
      note: 'Generate with: headscale preauthkeys create --reusable' })
  }
  // Gluetun VPN credentials — protocol choice determines which fields are needed
  if (form.infra.vpn === 'gluetun') {
    // Default VPN_TYPE to wireguard if not set
    if (!form.secrets['VPN_TYPE']) form.secrets['VPN_TYPE'] = 'wireguard'
    secrets.push({ key: 'VPN_SERVICE_PROVIDER', label: 'VPN Provider', required: true,
      type: 'text', placeholder: 'mullvad',
      note: 'Provider name: mullvad, nordvpn, surfshark, expressvpn, protonvpn, pia, etc.' })
    secrets.push({ key: 'VPN_TYPE', label: 'VPN Protocol', required: true,
      type: 'select', options: ['wireguard', 'openvpn'],
      note: 'Use WireGuard for Mullvad and most modern providers. OpenVPN for older setups.' })
    secrets.push({ key: 'OPENVPN_USER', label: 'VPN Username / Account number', required: false,
      type: 'text', placeholder: 'Required for OpenVPN. For Mullvad: your account number.',
      note: 'Leave blank if using WireGuard.' })
    secrets.push({ key: 'OPENVPN_PASSWORD', label: 'VPN Password', required: false,
      placeholder: 'Not required for Mullvad. Required for most other OpenVPN providers.',
      note: 'Leave blank for Mullvad or WireGuard.' })
    secrets.push({ key: 'WIREGUARD_PRIVATE_KEY', label: 'WireGuard Private Key', required: form.secrets['VPN_TYPE'] === 'wireguard',
      type: 'text', placeholder: 'base64-encoded key from your VPN provider',
      note: 'Required only for WireGuard protocol. Get from your provider dashboard.' })
    secrets.push({ key: 'SERVER_COUNTRIES', label: 'Server Country (optional)', required: false,
      type: 'text', placeholder: 'Netherlands',
      note: 'Preferred exit country. Leave blank for automatic selection.' })
  }
  // Komodo requires JWT secret and passkey (auto-generated)
  if (form.infra.management === 'komodo') {
    if (!form.secrets['KOMODO_JWT_SECRET']) form.secrets['KOMODO_JWT_SECRET'] = hex(32)
    if (!form.secrets['KOMODO_PASSKEY'])    form.secrets['KOMODO_PASSKEY']    = hex(16)
    secrets.push({ key: 'KOMODO_JWT_SECRET', label: 'Komodo JWT Secret', required: true,
      auto_generated: true, note: 'Auto-generated. Required for Komodo Core authentication.' })
    secrets.push({ key: 'KOMODO_PASSKEY', label: 'Komodo Passkey', required: true,
      auto_generated: true, note: 'Auto-generated. Core↔Periphery auth key.' })
  }
  if (form.infra.auth === 'tinyauth') {
    // TINYAUTH_SECRET: random signing key (auto-generated)
    if (!form.secrets['TINYAUTH_SECRET']) form.secrets['TINYAUTH_SECRET'] = hex(32)
    secrets.push({ key: 'TINYAUTH_SECRET', label: 'TinyAuth Session Secret', required: true,
      auto_generated: true, note: 'Auto-generated signing key. Do not share.' })
    // Username and password for TinyAuth login
    secrets.push({ key: 'TINYAUTH_USERNAME', label: 'Admin username', required: true,
      placeholder: 'admin', type: 'text',
      note: 'Username for the TinyAuth login page.' })
    secrets.push({ key: 'TINYAUTH_PASSWORD', label: 'Admin password', required: true,
      placeholder: 'Choose a strong password',
      note: 'Password for the TinyAuth login page. This will be bcrypt-hashed.' })
  }
  if (form.infra.auth === 'authelia') {
    if (!form.secrets['AUTHELIA_JWT_SECRET']) form.secrets['AUTHELIA_JWT_SECRET'] = hex(32)
    if (!form.secrets['AUTHELIA_SESSION_SECRET']) form.secrets['AUTHELIA_SESSION_SECRET'] = hex(32)
    secrets.push({ key: 'AUTHELIA_JWT_SECRET', label: 'Authelia JWT Secret', required: true,
      auto_generated: true, note: 'Auto-generated. Change only if migrating existing install.' })
    secrets.push({ key: 'AUTHELIA_SESSION_SECRET', label: 'Authelia Session Secret', required: true,
      auto_generated: true })
  }
  if (!form.secrets['POSTGRES_PASSWORD']) form.secrets['POSTGRES_PASSWORD'] = hex(16)
  secrets.push({ key: 'POSTGRES_PASSWORD', label: 'PostgreSQL Password', required: true,
    auto_generated: true, note: 'Used by Immich, Paperless-ngx, Authelia if selected.' })

  return secrets
})

const secretVisible = reactive<Record<string, boolean>>({})

// ── Catalog search for individual app selection (Stage 4) ─────────────────
const catalogSearchResults = computed(() => {
  if (!appSearch.value || appSearch.value.length < 2) return []
  const q = appSearch.value.toLowerCase()
  return catalogApps.value
    .filter((a: any) => a.key.includes(q) || a.display_name.toLowerCase().includes(q))
    .slice(0, 8)
})

function toggleIndividualApp(key: string) {
  const idx = form.individualApps.indexOf(key)
  if (idx >= 0) form.individualApps.splice(idx, 1)
  else form.individualApps.push(key)
}

// ── Auto-scroll current stage into view ───────────────────────────────────
import { watch, nextTick } from 'vue'
watch(currentStage, async () => {
  await nextTick()
  if (activeStageBtn.value && stageNavRef.value) {
    activeStageBtn.value.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }
})

function regenerateSecret(key: string) {
  form.secrets[key] = hex(32)
}

// ── Infra toggles ─────────────────────────────────────────────────────────
function toggleStack(id: string) {
  const idx = form.selectedStacks.indexOf(id)
  if (idx >= 0) form.selectedStacks.splice(idx, 1)
  else form.selectedStacks.push(id)
}

// ── App deploy tracking ───────────────────────────────────────────────────
const appInstallStatus = reactive<Record<string, string>>({})
const appInstallProgress = ref<Record<string, string>>({})
const secretsValidating = ref(false)
const secretsValidationResult = ref<any>(null)
const appInstallError = reactive<Record<string, string>>({})
const stackAppsToInstall = computed(() => {
  const apps: string[] = []
  for (const stackId of form.selectedStacks) {
    const stack = QUICK_STACKS_CONFIG.find(s => s.id === stackId)
    if (stack) apps.push(...stack.apps.map((a: string) => a.toLowerCase().replace(/ /g, '_')))
  }
  return [...new Set([...apps, ...form.individualApps])]
})

// ── Platform wizard deploy ────────────────────────────────────────────────
const running = ref(false)
const stackInstallDone = ref(false)
const installStarted = ref(false)
const appSearch = ref('')
const catalogApps = ref<any[]>([])
const activeStageBtn = ref<HTMLElement | null>(null)
const stageNavRef = ref<HTMLElement | null>(null)
const setupError = ref<string | null>(null)
const setupSuccess = ref(false)
const stepResults = ref<any[]>([])
const showReset = ref(false)
const certStatus = ref<{cert_found: boolean; message: string} | null>(null)
let certPollInterval: ReturnType<typeof setInterval> | null = null

async function pollCertStatus() {
  try {
    const r = await fetch('/api/v1/platform/cert-status')
    if (r.ok) {
      certStatus.value = await r.json()
      if (certStatus.value?.cert_found && certPollInterval) {
        clearInterval(certPollInterval)
        certPollInterval = null
      }
    }
  } catch {}
}

async function runWizard() {
  running.value = true
  setupError.value = null
  setupSuccess.value = false
  stepResults.value = []

  // If platform is already marked ready from a previous run, reset first
  // so the wizard can re-run (user clicked Deploy from the setup flow)
  try {
    const statusRes = await fetch('/api/v1/platform/status')
    const statusData = await statusRes.json()
    if (statusData.status === 'ready') {
      await fetch('/api/v1/platform/reset', { method: 'POST' })
      await new Promise(r => setTimeout(r, 500))
    }
  } catch {}

  try {
    const payload = {
      domain: form.domain,
      config_root: form.config_root,
      media_root: form.media_root,
      puid: form.puid,
      pgid: form.pgid,
      timezone: form.timezone,
      cert_resolver: form.cert_resolver,
      acme_email: form.acme_email || `admin@${form.domain}`,
      dns_provider: form.dns_provider,
      eab_kid: form.eab_kid,
      eab_hmac: form.eab_hmac,
      ntfy_url: form.ntfy_url,
      ntfy_topic: form.ntfy_topic,
      ntfy_enabled: form.ntfy_enabled,
      secrets: form.secrets,
      infra_selections: { ...form.infra, tunnels: form.tunnels },
      selected_stacks: form.selectedStacks,
    }
    // Start async wizard job — backend runs steps in background thread
    const startRes = await fetch('/api/v1/platform/wizard/run-async', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!startRes.ok) {
      const err = await startRes.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${startRes.status}`)
    }
    const { job_id } = await startRes.json()

    // Poll for step results every 800ms
    const result = await new Promise<any>((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`/api/v1/platform/wizard/status/${job_id}`)
          const status = await r.json()
          // Update steps in real time as they come in
          stepResults.value = status.steps || []
          if (status.done) {
            clearInterval(poll)
            resolve(status)
          }
        } catch (e) {
          clearInterval(poll)
          reject(e)
        }
      }, 800)
    })
    // result.steps already set via polling

    if (result.platform_ready) {
      setupSuccess.value = true
      forceSetup.value = true  // prevent isReady from switching to configured screen
      // Start polling cert status
      pollCertStatus()
      certPollInterval = setInterval(pollCertStatus, 10000) // every 10s
      await platformStore.fetchStatus()
      // Stage 8 is reached manually via Continue — don't auto-advance
    } else {
      // Find the failed step for context
      const failedStep = result.steps?.find((s: any) => s.status === 'error')
      const errMsg = result.error ?? failedStep?.message ?? 'Setup did not complete.'
      const errDetail = failedStep?.detail ? ` — ${failedStep.detail}` : ''
      setupError.value = errMsg + errDetail
    }
  } catch (e) {
    setupError.value = e instanceof Error ? e.message : String(e)
  } finally {
    running.value = false
  }
}


// App display info for Stage 8 install view
const catalogAppInfo = computed(() => {
  const map: Record<string, {name: string, icon: string, category: string}> = {}
  // Built-in fallbacks for quick stack apps
  const defaults: Record<string, {name: string, icon: string, category: string}> = {
    sonarr:      { name: 'Sonarr',        icon: '📺', category: 'arr' },
    radarr:      { name: 'Radarr',        icon: '🎬', category: 'arr' },
    prowlarr:    { name: 'Prowlarr',      icon: '🔍', category: 'arr' },
    sabnzbd:     { name: 'SABnzbd',       icon: '⬇️', category: 'downloader' },
    decypharr:   { name: 'Decypharr',     icon: '⚡', category: 'arr' },
    zilean:      { name: 'Zilean',        icon: '🕐', category: 'arr' },
    dumb:        { name: 'DUMB',          icon: '🌐', category: 'arr' },
    jellyfin:    { name: 'Jellyfin',      icon: '🎵', category: 'media' },
    seerr:       { name: 'Jellyseerr',    icon: '🔎', category: 'media' },
    immich:      { name: 'Immich',        icon: '📸', category: 'photos' },
    dozzle:      { name: 'Dozzle',        icon: '🪵', category: 'monitoring' },
    beszel:      { name: 'Beszel',        icon: '📊', category: 'monitoring' },
    scrutiny:    { name: 'Scrutiny',      icon: '💽', category: 'monitoring' },
    vaultwarden: { name: 'Vaultwarden',   icon: '🔐', category: 'productivity' },
    paperless_ngx:{ name: 'Paperless',   icon: '📄', category: 'productivity' },
    mealie:      { name: 'Mealie',        icon: '🍳', category: 'productivity' },
    ollama:      { name: 'Ollama',        icon: '🤖', category: 'ai' },
  }
  return { ...defaults }
})

function appDisplayName(key: string): string {
  return catalogAppInfo.value[key]?.name
    || (catalogApps.value.find((a: any) => a.key === key) as any)?.display_name
    || key.charAt(0).toUpperCase() + key.slice(1)
}
function appIcon(key: string): string {
  return catalogAppInfo.value[key]?.icon || '📦'
}

async function installStacks() {
  installStarted.value = true
  stackInstallDone.value = false
  appInstallProgress.value = {}

  const res = await fetch(`/api/v1/platform/wizard/stack-app-keys?stack_ids=${form.selectedStacks.join(',')}`)
  const data = await res.json()
  const keys: string[] = [...new Set([...(data.keys || []), ...form.individualApps])]

  if (keys.length === 0) {
    stackInstallDone.value = true
    return
  }

  for (const key of keys) appInstallStatus[key] = 'queued'

  // Install in parallel batches of 3 — faster than sequential, safe for different ports
  const CONCURRENCY = 3
  async function installOne(key: string) {
    appInstallStatus[key] = 'running'
    appInstallProgress.value[key] = 'Starting…'
    try {
      const r = await fetch('/api/v1/platform/wizard/install-stacks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stack_keys: [key] }),
      })
      const result = await r.json()
      const appResult = result.results?.[0]
      if (appResult?.ok) {
        appInstallStatus[key] = 'ok'
        appInstallProgress.value[key] = ''
      } else {
        // Check if the app is actually running despite error (health timeout race)
        try {
          const hc = await fetch(`/api/v1/health/apps/${key}/container-status`)
          const hd = await hc.json()
          if (hd.ready) {
            appInstallStatus[key] = 'ok'
            appInstallProgress.value[key] = 'Running (health check passed)'
            return
          }
        } catch {}
        appInstallStatus[key] = 'error'
        appInstallError[key] = appResult?.error || result.message || 'Install failed'
        appInstallProgress.value[key] = ''
      }
    } catch (e) {
      appInstallStatus[key] = 'error'
      appInstallError[key] = String(e)
      appInstallProgress.value[key] = ''
    }
  }

  // Run in batches of CONCURRENCY
  for (let i = 0; i < keys.length; i += CONCURRENCY) {
    await Promise.all(keys.slice(i, i + CONCURRENCY).map(installOne))
  }

  stackInstallDone.value = true
}

// ── Stage 9: Ollama auto-setup ─────────────────────────────────────────
const ollamaSetupJobId = ref<string | null>(null)
const ollamaSetupJob = ref<any>(null)
let ollamaSetupPoll: ReturnType<typeof setInterval> | null = null

// Model metadata — kept in sync with backend LLM_MODEL_RAM_MB
const ALL_OLLAMA_MODELS = [
  { value: 'smollm2:1.7b',  label: 'SmolLM2 1.7B (1.1GB)',  ram: 1.2, desc: 'fastest, minimal RAM' },
  { value: 'qwen2.5:3b',    label: 'Qwen 2.5 3B (1.9GB)',    ram: 2.2, desc: 'good balance' },
  { value: 'llama3.2:3b',   label: 'Llama 3.2 3B (2.0GB)',   ram: 2.5, desc: 'strong reasoning' },
  { value: 'phi4-mini',     label: 'Phi-4 Mini (2.5GB)',      ram: 3.0, desc: 'recommended for ≥8GB RAM' },
  { value: 'llama3.1:8b',   label: 'Llama 3.1 8B (4.7GB)',   ram: 5.0, desc: 'best quality, needs ≥12GB RAM or GPU' },
]

const ollamaModelOptions = computed(() => {
  // Use backend available_models list when present (accounts for GPU, bandwidth, stack)
  const backendModels = systemProfile.value?.available_models as string[] | undefined
  const recommended = systemProfile.value?.recommended_model || ''
  const gpu = systemProfile.value?.gpu_name || ''

  const models = ALL_OLLAMA_MODELS.map(m => {
    const backendApproved = !backendModels || backendModels.includes(m.value)
    const isRecommended = m.value === recommended
    const alreadyLoaded = (systemProfile.value?.ollama_models || []).includes(m.value)

    let suffix = m.desc
    if (alreadyLoaded) suffix = '✓ already downloaded'
    else if (isRecommended) suffix = '★ Recommended for your hardware'
    else if (!backendApproved) suffix = `⚠ may not fit (recommended: ${recommended || 'smaller model'})`

    return {
      ...m,
      label: `${m.label} — ${suffix}`,
      _recommended: isRecommended,
      _loaded: alreadyLoaded,
      _approved: backendApproved,
    }
  })
  // Sort: already loaded first, then recommended, then fits, then too large
  return models.sort((a, b) => {
    if (a._loaded !== b._loaded) return a._loaded ? -1 : 1
    if (a._recommended !== b._recommended) return a._recommended ? -1 : 1
    if (a._approved !== b._approved) return a._approved ? -1 : 1
    return 0
  })
})

async function startOllamaSetup() {
  ollamaSetupJob.value = { phase: 'starting', progress: 0, message: 'Starting…', done: false, ok: false }
  try {
    const r = await fetch('/api/v1/platform/wizard/setup-ollama', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: form.ollama_model }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    ollamaSetupJobId.value = d.job_id
    // Poll for progress
    if (ollamaSetupPoll) clearInterval(ollamaSetupPoll)
    ollamaSetupPoll = setInterval(async () => {
      try {
        const r2 = await fetch(`/api/v1/platform/wizard/ollama-status/${d.job_id}`)
        if (r2.ok) {
          const status = await r2.json()
          ollamaSetupJob.value = status
          if (status.done) {
            clearInterval(ollamaSetupPoll!)
            ollamaSetupPoll = null
          }
        }
      } catch {}
    }, 1500)
  } catch (e) {
    ollamaSetupJob.value = { phase: 'error', progress: 0, done: true, ok: false,
      message: `Failed to start: ${e}` }
  }
}

async function retryFailedApps() {
  const failed = stackAppsToInstall.value.filter(k => appInstallStatus[k] === 'error')
  stackInstallDone.value = false
  for (const key of failed) {
    appInstallStatus[key] = 'queued'
    appInstallError[key] = ''
  }
  for (const key of failed) {
    appInstallStatus[key] = 'running'
    try {
      const r = await fetch('/api/v1/platform/wizard/install-stacks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stack_keys: [key] }),
      })
      const result = await r.json()
      const appResult = result.results?.[0]
      if (appResult?.ok) {
        appInstallStatus[key] = 'ok'
      } else {
        appInstallStatus[key] = 'error'
        appInstallError[key] = appResult?.error || result.message || 'Install failed'
      }
    } catch (e) {
      appInstallStatus[key] = 'error'
      appInstallError[key] = String(e)
    }
  }
  stackInstallDone.value = true
}

async function saveLLMConfig() {
  if (form.llm_provider === 'none') return
  // Single source of truth for the per-provider api key. Previously there
  // were two `api_key:` properties on the request body (the second
  // shadowed the first), and the first's `apiKey` fallback defaulted
  // unrelated providers to `form.groq_api_key`. Both bugs gone now —
  // every supported provider has its key explicitly named.
  const apiKey =
    form.llm_provider === 'cerebras' ? form.cerebras_api_key
    : form.llm_provider === 'openai'  ? form.openai_api_key
    : form.llm_provider === 'awan'    ? form.awan_api_key
    : form.llm_provider === 'groq'    ? form.groq_api_key
    : undefined
  try {
    await fetch('/api/v1/platform/wizard/save-llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.llm_provider,
        api_key: apiKey,
        model: form.llm_provider === 'ollama' ? form.ollama_model
             : form.llm_provider === 'llamacpp' ? form.llamacpp_model
             : form.llm_provider === 'groq' ? form.groq_model
             : form.llm_provider === 'awan' ? form.awan_model
             : form.llm_provider === 'cerebras' ? form.cerebras_model
             : form.llm_provider === 'openai' ? form.openai_model
             : undefined,
        llamacpp_url: form.llm_provider === 'llamacpp' ? form.llamacpp_url : undefined,
      }),
    })
  } catch {}
}

async function doFullReset() {
  if (!confirm('FULL FACTORY RESET: This stops ALL containers, removes ALL compose fragments, and wipes the database. This cannot be undone. Continue?')) return
  showReset.value = false
  platformStore.clearStatus()  // sidebar clears instantly
  try {
    await fetch('/api/v1/platform/reset/full', { method: 'POST' })
    await platformStore.fetchStatus()
    forceSetup.value = true
    currentStage.value = 0
    maxReachedStage.value = 0
    form.domain = ''
    form.acme_email = ''
    form.eab_kid = ''
    form.eab_hmac = ''
    form.cert_resolver = 'letsencrypt'
    form.dns_provider = 'cloudflare'
    stepResults.value = []
    setupError.value = null
    setupSuccess.value = false
    prereqChecks.value = []
    await runPrereqChecks()
  } catch (e) {
    console.error('Full reset failed:', e)
  }
}

async function doReset() {
  showReset.value = false
  platformStore.clearStatus()  // sidebar clears instantly
  await platformApi.reset()
  await platformStore.fetchStatus()
  forceSetup.value = true
  currentStage.value = 0
  maxReachedStage.value = 0
  form.domain = ''
  form.acme_email = ''
  form.eab_kid = ''
  form.eab_hmac = ''
  form.cert_resolver = 'letsencrypt'
  form.dns_provider = 'cloudflare'
  stepResults.value = []
  setupError.value = null
  setupSuccess.value = false
  prereqChecks.value = []
  await runPrereqChecks()
}

onMounted(async () => {
  await runPrereqChecks()
  // Load system profile for AI stage recommendations
  try {
    const r = await fetch('/api/v1/settings/system')
    const d = await r.json()
    systemProfile.value = {
      ram_gb: Math.round((d.total_ram_mb || 0) / 1024),
      recommended_model: d.recommended_model || 'phi4-mini',
    }
  } catch {}
  // Pre-load LLM providers for Stage 9
  try {
    const r = await fetch('/api/v1/health/llm-providers')
    wizardLLMProviders.value = await r.json()
  } catch {}
  // Load catalog for individual app search
  try {
    const r = await fetch('/api/v1/catalog')
    const d = await r.json()
    catalogApps.value = Object.values(d).flat()
  } catch {}
})
</script>
