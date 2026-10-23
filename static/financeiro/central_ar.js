(function () {
    "use strict";

    const modal = document.getElementById("whatsapp-modal");
    const messageField = document.getElementById("whatsapp-message");
    const openWhatsApp = document.getElementById("open-whatsapp");
    const customerSummary = document.getElementById("modal-customer");
    const projectSummary = document.getElementById("modal-project");
    const amountSummary = document.getElementById("modal-amount");
    const dueSummary = document.getElementById("modal-due");
    let activePayload = null;

    if (!modal || !messageField || !openWhatsApp) {
        return;
    }

    function normalizePhone(phone) {
        const digits = phone.replace(/\D/g, "");
        return digits.startsWith("55") && (digits.length === 12 || digits.length === 13)
            ? digits
            : `55${digits}`;
    }

    function firstName(name) {
        return name.trim().split(/\s+/)[0] || "Cliente";
    }

    function approvedCopy(payload) {
        return `Olá, ${firstName(payload.cliente)}! Tudo bem? Estou entrando em contato sobre a parcela do projeto ${payload.projeto}, no valor de ${payload.valor}, com vencimento em ${payload.vencimento}. Podemos conversar?`;
    }

    function closeModal() {
        activePayload = null;
        modal.close();
    }

    document.querySelectorAll(".js-whatsapp-compose").forEach(function (button) {
        button.addEventListener("click", function () {
            activePayload = button.dataset;
            messageField.value = approvedCopy(activePayload);
            customerSummary.textContent = activePayload.cliente;
            projectSummary.textContent = activePayload.projeto;
            amountSummary.textContent = activePayload.valor;
            dueSummary.textContent = activePayload.vencimento;
            modal.showModal();
            messageField.focus({ preventScroll: true });
        });
    });

    document.querySelectorAll(".js-modal-close").forEach(function (button) {
        button.addEventListener("click", closeModal);
    });

    modal.addEventListener("cancel", function (event) {
        event.preventDefault();
        closeModal();
    });

    openWhatsApp.addEventListener("click", function () {
        if (!activePayload) {
            return;
        }
        const number = normalizePhone(activePayload.whatsapp);
        const message = encodeURIComponent(messageField.value);
        window.location.assign(`https://wa.me/${number}?text=${message}`);
    });
}());
