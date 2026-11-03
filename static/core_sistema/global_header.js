(() => {
    const toggle = document.querySelector("[data-global-menu-toggle]");
    if (!toggle) return;

    const navigation = document.getElementById(toggle.getAttribute("aria-controls"));
    if (!navigation) return;
    const finance = document.querySelector(".global-header__finance");
    const financeTrigger = finance?.querySelector("summary");

    const setMenuOpen = (isOpen) => {
        toggle.setAttribute("aria-expanded", String(isOpen));
        navigation.hidden = !isOpen;
    };

    toggle.addEventListener("click", () => {
        setMenuOpen(toggle.getAttribute("aria-expanded") !== "true");
    });

    navigation.addEventListener("click", (event) => {
        if (event.target.closest("a")) setMenuOpen(false);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;

        if (toggle.getAttribute("aria-expanded") === "true") {
            setMenuOpen(false);
            toggle.focus();
            return;
        }

        if (finance?.open) {
            finance.open = false;
            financeTrigger?.focus();
        }
    });
})();
