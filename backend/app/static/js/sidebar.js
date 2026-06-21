function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");

    if (window.innerWidth <= 900) {
        sidebar.classList.toggle("open");
    } else {
        sidebar.classList.toggle("collapsed");
    }
}