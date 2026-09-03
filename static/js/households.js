(function () {
    "use strict";

    const modal = document.getElementById("household-modal");
    if (!modal) {
        return;
    }

    const dialog = modal.querySelector(".household-dialog");
    const modalBody = modal.querySelector("[data-modal-body]");
    const loadingState = modal.querySelector("[data-modal-loading]");
    const errorState = modal.querySelector("[data-modal-error]");
    const modalContent = modal.querySelector("[data-modal-content]");
    const modalHouseholdId = modal.querySelector("[data-modal-household-id]");
    const memberRows = modal.querySelector("[data-member-rows]");
    const foodSecurityList = modal.querySelector("[data-food-security]");
    const resourcesList = modal.querySelector("[data-resources-protection]");
    const pwdIdentification = modal.querySelector("[data-pwd-identification]");
    const pwdIdentificationLabel = modal.querySelector(
        "[data-pwd-identification-label]"
    );
    const pwdMemberNames = modal.querySelector("[data-pwd-member-names]");
    const viewButtons = document.querySelectorAll(".record-view-button");
    const closeControls = modal.querySelectorAll("[data-modal-close]");

    let lastTrigger = null;
    let requestController = null;
    let requestSequence = 0;

    function displayValue(value) {
        if (value === null || value === undefined || value === "") {
            return "Not available";
        }
        return String(value);
    }

    function clearHouseholdContent() {
        modal.querySelectorAll("[data-overview]").forEach(function (element) {
            element.textContent = "";
        });
        memberRows.replaceChildren();
        foodSecurityList.replaceChildren();
        resourcesList.replaceChildren();
        pwdIdentification.hidden = true;
        pwdIdentificationLabel.textContent = "";
        pwdMemberNames.replaceChildren();
    }

    function setModalState(state) {
        const isLoading = state === "loading";
        loadingState.hidden = !isLoading;
        errorState.hidden = state !== "error";
        modalContent.hidden = state !== "content";
        modalBody.setAttribute("aria-busy", String(isLoading));
    }

    function renderPwdMembers(overview) {
        const pwdMembers = Array.isArray(overview.pwd_members)
            ? overview.pwd_members
            : [];
        const shouldShowMembers =
            overview.pwd_member_present === true && pwdMembers.length > 0;

        pwdIdentification.hidden = !shouldShowMembers;
        if (!shouldShowMembers) {
            return;
        }

        pwdIdentificationLabel.textContent =
            pwdMembers.length === 1 ? "Identified Member" : "Identified Members";

        const fragment = document.createDocumentFragment();
        pwdMembers.forEach(function (pwdMember) {
            const item = document.createElement("li");
            item.textContent = displayValue(pwdMember.name);
            fragment.appendChild(item);
        });
        pwdMemberNames.replaceChildren(fragment);
    }

    function renderOverview(overview) {
        modal.querySelectorAll("[data-overview]").forEach(function (element) {
            const fieldName = element.dataset.overview;
            element.textContent = displayValue(overview[fieldName]);
        });
        modalHouseholdId.textContent = displayValue(overview.household_id);
        renderPwdMembers(overview);
    }

    function renderMembers(members) {
        const fragment = document.createDocumentFragment();

        if (!members.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 4;
            cell.className = "member-empty";
            cell.textContent = "No household members available.";
            row.appendChild(cell);
            fragment.appendChild(row);
        } else {
            members.forEach(function (member) {
                const row = document.createElement("tr");
                [member.name, member.age, member.sex, member.relationship].forEach(
                    function (value) {
                        const cell = document.createElement("td");
                        cell.textContent = displayValue(value);
                        row.appendChild(cell);
                    }
                );
                fragment.appendChild(row);
            });
        }

        memberRows.replaceChildren(fragment);
    }

    function renderConditionList(container, conditions) {
        const fragment = document.createDocumentFragment();

        conditions.forEach(function (condition) {
            const row = document.createElement("div");
            const term = document.createElement("dt");
            const description = document.createElement("dd");
            term.textContent = condition.label;
            description.textContent = displayValue(condition.value);
            row.append(term, description);
            fragment.appendChild(row);
        });

        container.replaceChildren(fragment);
    }

    function renderHousehold(data) {
        renderOverview(data.overview);
        renderMembers(data.members);
        renderConditionList(foodSecurityList, data.conditions.food_security);
        renderConditionList(
            resourcesList,
            data.conditions.resources_and_protection
        );
        setModalState("content");
    }

    async function openHouseholdModal(button) {
        lastTrigger = button;
        requestSequence += 1;
        const currentRequest = requestSequence;

        if (requestController) {
            requestController.abort();
        }
        requestController = new AbortController();

        clearHouseholdContent();
        modalHouseholdId.textContent = button.dataset.householdId;
        setModalState("loading");
        modal.hidden = false;
        document.body.classList.add("modal-open");
        dialog.focus();

        try {
            const response = await fetch(button.dataset.detailsUrl, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                signal: requestController.signal,
            });

            if (!response.ok) {
                throw new Error("Household details request failed.");
            }

            const data = await response.json();
            if (currentRequest === requestSequence && !modal.hidden) {
                renderHousehold(data);
            }
        } catch (error) {
            if (
                error.name !== "AbortError" &&
                currentRequest === requestSequence &&
                !modal.hidden
            ) {
                clearHouseholdContent();
                setModalState("error");
            }
        }
    }

    function closeHouseholdModal() {
        if (modal.hidden) {
            return;
        }

        requestSequence += 1;
        if (requestController) {
            requestController.abort();
            requestController = null;
        }

        modal.hidden = true;
        document.body.classList.remove("modal-open");
        clearHouseholdContent();

        if (lastTrigger && document.contains(lastTrigger)) {
            lastTrigger.focus();
        }
        lastTrigger = null;
    }

    function keepFocusInsideModal(event) {
        if (event.key !== "Tab") {
            return;
        }

        const focusableElements = Array.from(
            dialog.querySelectorAll(
                'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
        ).filter(function (element) {
            return !element.hidden;
        });

        if (!focusableElements.length) {
            event.preventDefault();
            dialog.focus();
            return;
        }

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (
            event.shiftKey &&
            (document.activeElement === firstElement ||
                document.activeElement === dialog)
        ) {
            event.preventDefault();
            lastElement.focus();
        } else if (!event.shiftKey && document.activeElement === lastElement) {
            event.preventDefault();
            firstElement.focus();
        }
    }

    viewButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            openHouseholdModal(button);
        });
    });

    closeControls.forEach(function (control) {
        control.addEventListener("click", closeHouseholdModal);
    });

    document.addEventListener("keydown", function (event) {
        if (modal.hidden) {
            return;
        }
        if (event.key === "Escape") {
            event.preventDefault();
            closeHouseholdModal();
        } else {
            keepFocusInsideModal(event);
        }
    });
})();
