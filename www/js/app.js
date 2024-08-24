//@ts-check

import * as utils from "./utils.js"

export { }

/**
 * @param {string} q
 * @returns {Promise<string | null>}
*/
async function chat(q) {

    const url = "/api/chat?q=" + q

    let results = await utils.fetch_as_json(url)

    if (null != results) {
        return results["content"]
    }

    return null
}

/**
 * @param {any} item
 * @param {string} name
 * @returns {HTMLElement | null}
 */
function new_search_card(item, name) {

    const result = utils.new_template(name)

    if (result != null) {

        const title = result.querySelector("#title_link")

        let link = item.link

        if (title != null && title instanceof HTMLElement) {

            title.innerHTML = item.title

            if (link.includes("www.reddit.com")) {
                link = link.replace(/www/, "old");
            }

            title.setAttribute("href", link)
        }


        let url = new URL(link)

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
            body.innerHTML = item.snippet
        }
    }

    return result
}


/**
 * @param {HTMLElement} container
 * @param {string} q
 */
async function issue_query(container, q) {

    let url = "/api/search?q=" + q

    let results = await utils.fetch_as_json(url)

    if (results != null) {
        results.items.forEach(item => {
            let card = new_search_card(item, "search_result")

            if (card != null && card instanceof HTMLElement) {
                container.appendChild(card)
            }
        });

        utils.show_element(container)
    }
}

/**
 * @param {string} title
 * @param {string} url
 */
function update_url_bar(title, url) {
    window.history.pushState({ page: url }, title, url);
    document.title = title

}

/**
 * @param {HTMLElement} container
 * @param {HTMLInputElement} search_input
 */
async function onenter_cb(container, search_input) {

    const newUrl = '/search?q=' + search_input.value
    const pageTitle = 'Results for ' + search_input.value

    update_url_bar(pageTitle, newUrl)

    utils.remove_all_children(container)
    container.setAttribute("q", "")
    utils.hide_element(container)

    if (search_input.value.length < 2) {
        // input too short to return anything meaningful
    }
    else {

        container.setAttribute("q", search_input.value)
        await issue_query(container, search_input.value)
    }
}


/**
 * @param {string | null} q
 */
function init_search_bar(q) {

    const container = document.getElementById('results')

    if (container != null && container instanceof HTMLElement) {

        const search_input = document.getElementById('search-input');

        if (search_input != null && search_input instanceof HTMLInputElement) {

            search_input.addEventListener("keyup", function (e) {
                if (e.key == "Enter") {
                    //
                    // hide the keyboard
                    //
                    if (true == utils.isMobile()) {
                        search_input.blur()
                    }
                    onenter_cb(container, search_input)
                }
                else if (e.key == "Escape") {
                    search_input.value = ""
                }
            })

            if (null != q) {
                search_input.value = q
                onenter_cb(container, search_input)
            }
        }
        else {
            console.log("couldn't find the search input")
        }
    }
    else {
        console.log("couldn't find the result container")
    }
}


/**
 * @param {string} q
 */
async function init_ai(q) {

    const resp = await chat(q)

    if (null != resp) {

        const result_container = document.getElementById("results")

        if (result_container != null && result_container instanceof HTMLElement) {

            const container = document.getElementById('chat_text')

            if (container != null && container instanceof HTMLElement) {
                container.innerHTML = marked.parse(resp)
            }

            utils.show_element(result_container)
        }
    }
}

async function main() {

    var q = null

    const search = window.location.search;

    if (search != null && search.length > 0) {
        const urlParams = new URLSearchParams(search);
        q = urlParams.get('q')
    }

    if (window.location.pathname == "/ai.html") {
        if (null != q) {
            await init_ai(q)
        }
    }
    else {
        init_search_bar(q)
    }
}

await main()
