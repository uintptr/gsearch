//@ts-check

import * as utils from "./utils.js"

export { }

const HIGH_VALUE_DOMAINS = {
    "wikipedia.org": 1,
    "github.com": 2,
    "imdb.com": 3,
    "stackoverflow.com": 3,
}

/**
 * @param {any} item
 * @returns {HTMLElement | null}
 */
function new_search_card(item) {

    const result = utils.new_template("search_result")

    if (result != null) {

        const title = result.querySelector("#title_link")

        if (title != null && title instanceof HTMLElement) {
            title.innerHTML = item.title

            title.setAttribute("href", item.link)
        }


        let url = new URL(item.link)

        // decomposed URL
        let components = url.pathname.split("/")
        components[0] = url.hostname
        let parts = components.join(" > ")
        utils.set_selector_text(result, "#url_parts", parts)


        // favicon
        let favicon = result.querySelector("#favicon")

        if (favicon != null && favicon instanceof HTMLImageElement) {
            let url_str = url.protocol + "//" + url.hostname + "/favicon.ico"
            favicon.setAttribute("src", "/api/favicon?url=" + url_str)
        }

        const body = result.querySelector("#result_text")

        if (body != null && body instanceof HTMLElement) {
            body.innerHTML = item.htmlSnippet
        }
    }

    return result
}


/**
 * @param {any[]} results
 * @returns {any[]}
 */
function promote_results(results) {

    var idx = 100

    for (const r of results) {
        r.score = idx
        idx++
    }

    for (let k in HIGH_VALUE_DOMAINS) {
        for (var i = 0; i < results.length; i++) {
            if (results[i].link.includes(k)) {
                results[i].score = HIGH_VALUE_DOMAINS[k]
            }
        }
    }

    return results.sort((a, b) => a.score - b.score)
}


/**
 * @param {HTMLElement} container
 * @param {string} q
 * @param {IntersectionObserver} observer
 * @param {{ postMessage: (arg0: string[]) => void; }} worker
 */
async function issue_query(container, worker, q, observer, start_idx = 1) {

    let url = "/api/search?q=" + q

    //worker.postMessage(["chat", q])

    let results = await utils.fetch_as_json(url)

    if (results != null) {

        if (results.hasOwnProperty("spelling")) {
            const alert = utils.new_template("alert_spelling")

            if (alert != null) {
                let actual = results.spelling.correctedQuery
                alert.innerHTML = `Results for "${actual}"`
                container.appendChild(alert)
            }
        }

        let promoted_results = promote_results(results.items)

        for (const item of promoted_results) {

            let card = new_search_card(item)

            if (card != null && card instanceof HTMLElement) {

                card.setAttribute("idx", start_idx.toString())

                observer.observe(card)
                container.appendChild(card)
            }

            start_idx++
        }
    }
}

/**
 * @param {string} title
 * @param {string} url
 */
function update_url_bar(title, url) {
    window.history.pushState({ page: url }, title, url);

}

/**
 * @param {HTMLElement} container
 * @param {HTMLInputElement} search_input
 * @param {IntersectionObserver} observer
 * @param {Worker} worker
 */
async function onenter_cb(container, worker, search_input, observer) {

    const newUrl = '/search?q=' + search_input.value
    const pageTitle = 'Search Results for ' + search_input.value

    update_url_bar(pageTitle, newUrl)

    utils.remove_all_children(container)
    container.setAttribute("q", "")

    if (search_input.value.length < 2) {
        // input too short to return anything meaningful
    }
    else {

        container.setAttribute("q", search_input.value)
        await issue_query(container, worker, search_input.value, observer)
    }
}

/**
 * @param {IntersectionObserver} observer
 * @param {IntersectionObserverEntry[]} elements
 */
async function observerCallback(observer, elements) {

    for (const elem of elements) {

        let idx_str = elem.target.getAttribute("idx")
        let idx = 1

        if (null != idx_str) {
            idx = parseInt(idx_str)
        }

        if (true == elem.isIntersecting) {
            const container = document.getElementById("search-results-container")

            if (container != null && container instanceof HTMLElement) {

                //console.log("idx= " + idx + " children=" + container.children.length)
                /*
                if (idx == container.children.length) {
                    let q = container.getAttribute("q")

                    if (q != null) {
                        await issue_query(container, q, observer, idx + 1)
                    }
                }
                */
            }
        }
    }
}

function init_observer() {

    const options = {
        root: null,
        rootMargin: "10px",
        threshold: 0.5
    };

    const observer = new IntersectionObserver(async function (elements) {
        observerCallback(this, elements)
    }, options)

    const targets = document.querySelectorAll(".hstack")

    for (const target of targets) {
        observer.observe(target)
    }

    return observer
}

/**
 * @param {IntersectionObserver} observer
 * @param {Worker} worker
 * @param {string | null} q
 */
function init_search_bar(observer, worker, q) {

    const container = document.getElementById('search-results-container')

    if (container != null && container instanceof HTMLElement) {
        const searchBar = document.getElementById('search_bar');

        if (searchBar != null && searchBar instanceof HTMLInputElement) {

            searchBar.addEventListener("keyup", function (e) {
                if (e.key == "Enter") {


                    //
                    // hide the keyboard
                    //
                    if (true == utils.isMobile()) {
                        searchBar.blur()
                    }
                    onenter_cb(container, worker, searchBar, observer)
                }
                else if (e.key == "Escape") {
                    searchBar.value = ""
                }
            })

            if (null != q) {
                searchBar.value = q
                onenter_cb(container, worker, searchBar, observer)
            }

            const clear_btn = document.getElementById("clear_search")

            if (clear_btn != null && clear_btn instanceof HTMLButtonElement) {
                clear_btn.addEventListener("click", function (e) {
                    searchBar.value = ""
                    utils.remove_all_children(container)
                    searchBar.focus()
                    update_url_bar("GSearch", "/")
                })
            }
        }

    }

    const sb_container = document.getElementById("search_bar_container")

    /*
    if (sb_container != null && sb_container instanceof HTMLElement) {
        if (true == utils.isMobile()) {
            sb_container.classList.add("fixed-bottom")
        }
    }
    */
}

/**
 * @param {string} msg
 */
async function add_chat_message(msg) {

    const search_results = document.getElementById("search-results-container")

    if (search_results != null && search_results instanceof HTMLElement) {

        const container = utils.new_template("chatgpt_sandbox")

        if (container != null) {

            const chat = container.querySelector("#chat_msg")

            if (chat != null && chat instanceof HTMLElement) {
                //@ts-ignore
                chat.innerHTML = marked.parse(msg)
                search_results.insertBefore(container, search_results.firstChild)
            }
        }
    }
}

async function main() {
    let observer = init_observer()

    var q = null

    const queryString = window.location.search;

    if (queryString != null && queryString.length > 0) {
        const urlParams = new URLSearchParams(queryString);
        q = urlParams.get('q')
    }

    const worker = new Worker('/js/bg.js');

    init_search_bar(observer, worker, q)

    // listen for messages from the web worker
    worker.onmessage = function (event) {

        let data = event.data

        if (data != null && data instanceof Array) {
            if ("chat" == data[0]) {
                add_chat_message(data[1])
            }
        }
    };
}

await main()
