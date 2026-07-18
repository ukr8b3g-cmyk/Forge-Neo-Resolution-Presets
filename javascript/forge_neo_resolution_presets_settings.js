(() => {
  const initialize = root => {
    if (!root || root.dataset.fnpReady) return;
    root.dataset.fnpReady = "1";

    const api = (path, options = {}) => fetch(`/fnp-resolution-presets/settings/${path}`, {
      headers: {"Content-Type": "application/json"}, ...options
    }).then(async response => {
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.message || "Request failed");
      return body;
    });
    const status = root.querySelector("#fnp-settings-status");
    const profileSelect = root.querySelector("#fnp-settings-profile");
    const presetList = root.querySelector("#fnp-settings-presets");
    const backupSelect = root.querySelector("#fnp-settings-backup");
    const historyList = root.querySelector("#fnp-settings-history");
    const profileDialog = root.querySelector("#fnp-settings-profile-dialog");
    const profileNameInput = root.querySelector("#fnp-settings-profile-name");
    const profileDialogError = root.querySelector("#fnp-settings-profile-dialog-error");
    let state = null;
    let profileIndex = 0;
    let dragIndex = null;
    let dirty = false;
    let lastDeletedPreset = null;
    let validationErrors = {global: [], rows: {}};

    const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    }[char]));
    const selectedProfile = () => state && state.profiles && state.profiles.profiles[profileIndex];
    const profileKey = (profileIndexValue, presetIndex) => `${profileIndexValue}:${presetIndex}`;

    const setStatus = (message, tone = "", undo = false) => {
      if (!status) return;
      status.className = `fnp-settings-status${tone ? ` ${tone}` : ""}`;
      status.textContent = "";
      status.appendChild(document.createTextNode(message));
      if (undo) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.action = "undo-delete";
        button.textContent = "Undo";
        status.appendChild(document.createTextNode(" · "));
        status.appendChild(button);
      }
    };

    const markDirty = () => {
      dirty = true;
      validationErrors = {global: [], rows: {}};
      setStatus("Unsaved changes", "dirty");
    };

    const isUsedName = name => state.profiles.profiles.some(profile => profile.name.toLowerCase() === name.toLowerCase());
    const uniqueProfileName = baseName => {
      const base = baseName.trim() || "New Profile";
      if (!isUsedName(base)) return base;
      let suffix = 2;
      let candidate = `${base} ${suffix}`;
      while (isUsedName(candidate)) candidate = `${base} ${++suffix}`;
      return candidate;
    };

    const preferredResolutions = [
      [1024, 1024], [1024, 1344], [1344, 1024], [896, 1152], [1152, 896],
      [832, 1216], [1216, 832], [768, 1280], [1280, 768], [1280, 1280],
      [960, 1280], [1280, 960], [1040, 1552], [1552, 1040]
    ];
    const findFreePreset = profile => {
      const used = new Set(profile.presets.map(preset => `${preset.width}x${preset.height}`));
      for (const [width, height] of preferredResolutions) {
        if (!used.has(`${width}x${height}`)) return {width, height};
      }
      for (let size = 512; size <= 4096; size += 8) {
        if (!used.has(`${size}x${size}`)) return {width: size, height: size};
      }
      throw new Error("追加できる解像度がありません");
    };

    const validateProfiles = profilesConfig => {
      const global = [];
      const rows = {};
      const profiles = profilesConfig && Array.isArray(profilesConfig.profiles) ? profilesConfig.profiles : [];
      if (!profiles.length) global.push("Profileは1件以上必要です");
      const names = new Map();
      profiles.forEach((profile, index) => {
        const name = String(profile.name ?? "").trim();
        if (!name) global.push(`Profile ${index + 1}: 名前を入力してください`);
        else if (name.length > 32) global.push(`Profile ${index + 1}: 名前は32文字以内です`);
        const normalizedName = name.toLowerCase();
        if (normalizedName && names.has(normalizedName)) global.push(`Profile名が重複しています: ${name}`);
        if (normalizedName) names.set(normalizedName, index);
        const presets = Array.isArray(profile.presets) ? profile.presets : [];
        if (!presets.length) global.push(`${name || `Profile ${index + 1}`}: Presetは1件以上必要です`);
        if (presets.length > 14) global.push(`${name || `Profile ${index + 1}`}: Presetは14件以内です`);
        const pairs = new Set();
        presets.forEach((preset, presetIndex) => {
          const errors = [];
          const width = Number(preset.width);
          const height = Number(preset.height);
          if (!Number.isInteger(width) || width < 16 || width > 16384 || width % 8 !== 0) errors.push("Width must be an integer from 16 to 16384 and a multiple of 8");
          if (!Number.isInteger(height) || height < 16 || height > 16384 || height % 8 !== 0) errors.push("Height must be an integer from 16 to 16384 and a multiple of 8");
          const pair = `${width}x${height}`;
          if (errors.length === 0 && pairs.has(pair)) errors.push("Duplicate resolution");
          if (errors.length === 0) pairs.add(pair);
          if (errors.length) rows[profileKey(index, presetIndex)] = errors;
        });
      });
      const defaultName = String(profilesConfig && profilesConfig.default_profile || "");
      if (!profiles.some(profile => profile.name === defaultName)) global.push("Default profileが見つかりません");
      return {global, rows, valid: global.length === 0 && Object.keys(rows).length === 0};
    };

    const renderProfiles = () => {
      if (!state || !state.profiles) return;
      const profiles = state.profiles.profiles || [];
      profileSelect.innerHTML = profiles.map((profile, index) => `<option value="${index}">${escape(profile.name)}${profile.name === state.profiles.default_profile ? " (default)" : ""}</option>`).join("");
      profileSelect.value = String(profileIndex);
      const profile = selectedProfile();
      if (!profile) {
        presetList.innerHTML = "<div class=\"fnp-settings-empty\">Profileがありません</div>";
        return;
      }
      const presets = Array.isArray(profile.presets) ? profile.presets : [];
      presetList.innerHTML = presets.map((preset, index) => {
        const errors = validationErrors.rows[profileKey(profileIndex, index)] || [];
        const invalid = errors.length ? " invalid" : "";
        const deleteDisabled = presets.length <= 1 ? " disabled" : "";
        const duplicateDisabled = presets.length >= 14 ? " disabled" : "";
        const width = Number.isFinite(Number(preset.width)) ? preset.width : "";
        const height = Number.isFinite(Number(preset.height)) ? preset.height : "";
        return `<div class="fnp-settings-preset-row${invalid}" draggable="true" tabindex="0" data-index="${index}" aria-label="${index < 9 ? "Main" : "More Portrait"} ${index + 1}">
          <span class="fnp-settings-drag" title="Drag to reorder" aria-label="Drag to reorder">↕</span>
          <span class="fnp-settings-slot">${index < 9 ? "Main" : "More"} ${index + 1}</span>
          <input type="number" min="16" max="16384" step="8" data-field="width" aria-label="${index + 1} Width" value="${escape(width)}">
          <span aria-hidden="true">×</span>
          <input type="number" min="16" max="16384" step="8" data-field="height" aria-label="${index + 1} Height" value="${escape(height)}">
          <button type="button" data-action="duplicate-preset" data-index="${index}"${duplicateDisabled}>Duplicate</button>
          <button type="button" data-action="delete-preset" data-index="${index}" class="danger-outline" aria-label="Delete preset ${index + 1}"${deleteDisabled}>Delete</button>
          ${errors.length ? `<div class="fnp-settings-row-error" role="alert">${errors.map(escape).join(" · ")}</div>` : ""}
        </div>`;
      }).join("");
      const addButton = root.querySelector('[data-action="add-preset"]');
      if (addButton) {
        addButton.disabled = presets.length >= 14;
        addButton.title = presets.length >= 14 ? "A Profile can contain up to 14 presets" : "Add a preset";
      }
      const deleteProfileButton = root.querySelector('[data-action="delete-profile"]');
      if (deleteProfileButton) deleteProfileButton.disabled = profiles.length <= 1;
    };

    const renderBackups = () => {
      const backups = state && state.backups || [];
      backupSelect.innerHTML = backups.length
        ? backups.map(name => `<option value="${escape(name)}">${escape(name)}</option>`).join("")
        : "<option value=\"\">No backups available</option>";
      const restoreButton = root.querySelector('[data-action="restore-backup"]');
      if (restoreButton) restoreButton.disabled = !backups.length;
    };

    const renderHistory = () => {
      const history = state && state.history || [];
      historyList.innerHTML = history.length ? history.map(item => `
        <div class="fnp-settings-history-row"><strong>${escape(item.width)}×${escape(item.height)}</strong><span>${escape(item.profile || "")} · ${escape(item.tab || "")}</span><small>${escape(item.timestamp || "")}</small></div>`).join("") : "<div class=\"fnp-settings-empty\">No history</div>";
    };

    const render = () => {
      renderProfiles();
      renderBackups();
      renderHistory();
      const randomDefault = root.querySelector("#fnp-settings-random-default");
      const randomCustom = root.querySelector("#fnp-settings-random-custom");
      if (randomDefault) randomDefault.checked = Boolean(state.behavior.randomize_default);
      if (randomCustom) randomCustom.checked = Boolean(state.behavior.randomize_user_presets);
    };

    const closeProfileDialog = () => {
      profileDialog.hidden = true;
      profileDialogError.textContent = "";
    };
    const openProfileDialog = () => {
      profileDialog.hidden = false;
      profileDialogError.textContent = "";
      profileNameInput.value = "";
      profileNameInput.focus();
    };

    const createProfile = () => {
      const name = profileNameInput.value.trim();
      if (!name || name.length > 32) {
        profileDialogError.textContent = "Profile name must be 1–32 characters.";
        return;
      }
      if (isUsedName(name)) {
        profileDialogError.textContent = "同名のProfileがあります";
        return;
      }
      const profile = {name, presets: [findFreePreset({presets: []})]};
      state.profiles.profiles.push(profile);
      profileIndex = state.profiles.profiles.length - 1;
      closeProfileDialog();
      markDirty();
      renderProfiles();
    };

    const movePreset = (fromIndex, toIndex) => {
      const presets = selectedProfile() && selectedProfile().presets;
      if (!presets || fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= presets.length || toIndex >= presets.length) return;
      const [moved] = presets.splice(fromIndex, 1);
      presets.splice(toIndex, 0, moved);
      markDirty();
      renderProfiles();
      const row = presetList.querySelector(`[data-index="${toIndex}"]`);
      if (row) row.focus();
    };

    const load = async () => {
      try {
        const response = await api("state");
        state = response.state;
        profileIndex = Math.max(0, state.profiles.profiles.findIndex(profile => profile.name === state.profiles.default_profile));
        dirty = false;
        validationErrors = {global: [], rows: {}};
        render();
        setStatus("Saved", "saved");
      } catch (error) {
        setStatus(error.message, "error");
      }
    };

    document.addEventListener("click", event => {
      const button = event.target.closest && event.target.closest("button");
      if (!dirty || !button || button.textContent.trim() !== "Reload UI") return;
      if (!confirm("Reload UIすると未保存のProfile編集が失われます。続行しますか？")) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
    window.addEventListener("beforeunload", event => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });

    root.addEventListener("input", event => {
      const row = event.target.closest(".fnp-settings-preset-row");
      if (!row || !event.target.dataset.field || !selectedProfile()) return;
      const value = event.target.value.trim();
      selectedProfile().presets[Number(row.dataset.index)][event.target.dataset.field] = value === "" ? null : Number(value);
      markDirty();
    });

    profileSelect.addEventListener("change", () => {
      profileIndex = Number(profileSelect.value);
      validationErrors = {global: [], rows: {}};
      renderProfiles();
    });

    presetList.addEventListener("dragstart", event => {
      const row = event.target.closest(".fnp-settings-preset-row");
      dragIndex = row ? Number(row.dataset.index) : null;
      if (row) row.classList.add("dragging");
    });
    presetList.addEventListener("dragover", event => event.preventDefault());
    presetList.addEventListener("drop", event => {
      event.preventDefault();
      const row = event.target.closest(".fnp-settings-preset-row");
      if (!row || dragIndex === null) return;
      movePreset(dragIndex, Number(row.dataset.index));
      dragIndex = null;
    });
    presetList.addEventListener("dragend", event => {
      const row = event.target.closest(".fnp-settings-preset-row");
      if (row) row.classList.remove("dragging");
      dragIndex = null;
    });
    presetList.addEventListener("keydown", event => {
      const row = event.target.closest(".fnp-settings-preset-row");
      if (!row || !event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const index = Number(row.dataset.index);
      movePreset(index, event.key === "ArrowUp" ? index - 1 : index + 1);
    });

    root.addEventListener("keydown", event => {
      if (event.key === "Escape" && !profileDialog.hidden) closeProfileDialog();
      if (event.key === "Enter" && event.target === profileNameInput) createProfile();
    });

    root.addEventListener("click", async event => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      try {
        if (action === "add-profile") {
          openProfileDialog();
        } else if (action === "cancel-profile-dialog") {
          closeProfileDialog();
        } else if (action === "create-profile") {
          createProfile();
        } else if (action === "duplicate-profile") {
          const source = selectedProfile();
          if (!source) return;
          state.profiles.profiles.splice(profileIndex + 1, 0, {
            name: uniqueProfileName(`${source.name} Copy`),
            presets: source.presets.map(preset => ({...preset}))
          });
          profileIndex += 1;
          markDirty();
          renderProfiles();
        } else if (action === "delete-profile") {
          const profile = selectedProfile();
          if (!profile || state.profiles.profiles.length <= 1 || !confirm(`Delete profile “${profile.name}”?`)) return;
          const deletedName = profile.name;
          state.profiles.profiles.splice(profileIndex, 1);
          if (state.profiles.default_profile === deletedName) state.profiles.default_profile = state.profiles.profiles[0].name;
          profileIndex = Math.min(profileIndex, state.profiles.profiles.length - 1);
          markDirty();
          renderProfiles();
        } else if (action === "set-default") {
          const profile = selectedProfile();
          if (!profile) return;
          state.profiles.default_profile = profile.name;
          markDirty();
          renderProfiles();
        } else if (action === "add-preset") {
          const profile = selectedProfile();
          if (!profile || profile.presets.length >= 14) throw new Error("A Profile can contain up to 14 presets");
          profile.presets.push(findFreePreset(profile));
          markDirty();
          renderProfiles();
        } else if (action === "duplicate-preset") {
          const profile = selectedProfile();
          if (!profile || profile.presets.length >= 14) throw new Error("A Profile can contain up to 14 presets");
          const index = Number(button.dataset.index);
          profile.presets.splice(index + 1, 0, {...profile.presets[index]});
          markDirty();
          renderProfiles();
        } else if (action === "delete-preset") {
          const profile = selectedProfile();
          if (!profile || profile.presets.length <= 1) throw new Error("Profileには1件以上必要です");
          const index = Number(button.dataset.index);
          lastDeletedPreset = {profileIndex, index, preset: {...profile.presets[index]}};
          profile.presets.splice(index, 1);
          markDirty();
          renderProfiles();
          setStatus("Preset deleted", "dirty", true);
        } else if (action === "undo-delete") {
          if (!lastDeletedPreset || !state.profiles.profiles[lastDeletedPreset.profileIndex]) return;
          const profile = state.profiles.profiles[lastDeletedPreset.profileIndex];
          profile.presets.splice(Math.min(lastDeletedPreset.index, profile.presets.length), 0, lastDeletedPreset.preset);
          lastDeletedPreset = null;
          markDirty();
          renderProfiles();
        } else if (action === "save-profiles") {
          const result = validateProfiles(state.profiles);
          validationErrors = {global: result.global, rows: result.rows};
          if (!result.valid) {
            renderProfiles();
            const firstError = result.global[0] || Object.values(result.rows)[0]?.[0] || "入力内容を確認してください";
            setStatus(`Could not save: ${firstError}`, "error");
            return;
          }
          const response = await api("profiles", {method: "POST", body: JSON.stringify(state.profiles)});
          state = response.state;
          profileIndex = Math.max(0, state.profiles.profiles.findIndex(profile => profile.name === state.profiles.default_profile));
          dirty = false;
          lastDeletedPreset = null;
          validationErrors = {global: [], rows: {}};
          render();
          setStatus(response.message || "Saved · backup created", "saved");
        } else if (action === "restore-defaults") {
          if (!confirm("Restore built-in profiles? Unsaved changes will be lost.")) return;
          const response = await api("restore-defaults", {method: "POST"});
          state = response.state;
          profileIndex = 0;
          dirty = false;
          validationErrors = {global: [], rows: {}};
          render();
          setStatus(response.message || "Built-in profiles restored", "saved");
        } else if (action === "backup") {
          const draftProfiles = state.profiles;
          const response = await api("backup", {method: "POST"});
          state = {...state, ...response.state, profiles: draftProfiles};
          renderBackups();
          setStatus(dirty ? "Backup created · Unsaved changes" : (response.message || "Backup created"), dirty ? "dirty" : "saved");
        } else if (action === "restore-backup") {
          if (!backupSelect.value || !confirm("Restore the selected backup? Unsaved changes will be lost.")) return;
          const response = await api("restore-backup", {method: "POST", body: JSON.stringify({name: backupSelect.value})});
          state = response.state;
          profileIndex = 0;
          dirty = false;
          validationErrors = {global: [], rows: {}};
          render();
          setStatus(response.message || "Backup restored", "saved");
        } else if (action === "save-behavior") {
          const response = await api("behavior", {method: "POST", body: JSON.stringify({
            randomize_default: root.querySelector("#fnp-settings-random-default").checked,
            randomize_user_presets: root.querySelector("#fnp-settings-random-custom").checked
          })});
          state.behavior = response.behavior;
          setStatus(dirty ? "Randomize settings saved · Unsaved profile changes remain" : (response.message || "Randomize settings saved"), dirty ? "dirty" : "saved");
        } else if (action === "clear-history") {
          if (!confirm("Clear resolution history?")) return;
          const response = await api("history/clear", {method: "POST"});
          state = response.state;
          renderHistory();
          setStatus(response.message || "History cleared", "saved");
        }
      } catch (error) {
        setStatus(error.message, "error");
      }
    });

    load();
  };

  const scan = () => document.querySelectorAll("#fnp_settings_editor").forEach(initialize);
  const ready = () => {
    scan();
  };
  if (typeof onUiLoaded === "function") onUiLoaded(ready);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready, {once: true});
  else ready();
  if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(ready);
  else if (document.documentElement) new MutationObserver(ready).observe(document.documentElement, {childList: true, subtree: true});
})();
