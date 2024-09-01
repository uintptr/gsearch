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
            console.error("couldn't find the search input")
        }
    }
    else {
        console.error("couldn't find the result container")
    }
}

/**
 * @param {HTMLElement} container
 * @param {string} response
 * @param {boolean} markdown
 * @param {string | null} chat_source
 */
function add_chat_response(container, response, markdown, chat_source = null) {

    utils.show_element(container)

    const result = utils.new_template("search_result")

    if (null != result) {

        // to rebuild the context
        if (null != chat_source) {
            result.setAttribute("chat-source", chat_source)
            result.setAttribute("chat-data", response)
        }

        const text_container = result.querySelector("#chat_text")

        if (text_container != null && text_container instanceof HTMLElement) {

            if (true == markdown) {
                text_container.innerHTML = marked.parse(response) // @ts-ignore
            }
            else {
                text_container.innerText = response
            }

            container.appendChild(result)
        }
        else {
            console.error("unable to find text container")
        }
    }
    else {
        console.error("couldn't find template")
    }
}

/**
* @param {HTMLElement} container
* @returns {Object[]}
*/
function get_chat_context(container) {
    let context_list = []

    for (var i = 0; i < container.childElementCount; i++) {
        let child = container.children[i]

        if (child instanceof HTMLElement) {
            const chat_source = child.getAttribute("chat-source")
            const chat_data = child.getAttribute("chat-data")

            if (null != chat_source && null != chat_data) {

                const entry = {
                    "role": chat_source,
                    "content": chat_data
                }

                context_list.push(entry)
            }
        }
    }

    return context_list
}


/**
* @returns {Promise<string | null>}
*/
async function bookmarks_list() {
    let res_str = null

    const url = "/api/bookmaks"

    const bookmarks = await utils.fetch_as_json("/api/bookmarks")

    if (null != bookmarks && bookmarks.length > 0) {

        res_str = "| Name | Shortcut | URL |\n"
        res_str += "|:------|:----------|:-----|\n"

        bookmarks.forEach(item => {
            res_str += `|${item["name"]}|${item["shortcut"]}|${item["url"]}|\n`
        })
    }

    console.log(res_str)

    return res_str
}

/**
* @param {string| null} params
* @returns {Promise<string | null>}
*/
async function bookmarks_command(params) {
    let res_str = null

    if (null == params) {
        res_str = await bookmarks_list()
    }
    else if (params.startsWith("add")) {
    }
    else if (params.startsWith("rem")) {
    }

    return res_str
}



/**
* @param {HTMLElement} container
* @param {string} user_input
*/
async function on_chat_cb(container, user_input) {

    let req = {}
    let chat_source = null
    let markdown = false
    let res_str = null

    if (user_input.startsWith("/")) {
        const cmd_name = user_input.split(' ', 1)[0]

        req["cmd"] = cmd_name

        if (user_input.length > cmd_name.length) {
            req["args"] = user_input.substring(cmd_name.length + 1)
        }
    }
    else {
        chat_source = "system"

        req["cmd"] = "/chat"
        req["args"] = user_input
        req["history"] = get_chat_context(container)

        add_chat_response(container, user_input, true, "user")
    }

    if (req["cmd"] == "/reset" || req["cmd"] == "/clear") {
        utils.remove_all_children(container)
        utils.hide_element(container)
    }
    else if (req["cmd"] == "/bookmarks") {

        let args = null

        if ("args" in req) {
            args = req["args"]
        }

        res_str = await bookmarks_command(args)
        markdown = true
    }
    else {
        let res = await utils.fetch_post_json("/api/cmd", req)

        if ("error" in res && "" != res["error"]) {
            console.error(res["error"])
        }

        res_str = res["data"]

        if ("markdown" in res) {
            markdown = res["markdown"]
        }
    }

    if (null != res_str) {
        add_chat_response(container, res_str, markdown, chat_source)
    }
}


function init_cmd_line() {

    const results_container = document.getElementById("results")

    if (results_container != null && results_container instanceof HTMLElement) {

        const cmd_input = document.getElementById('cmd_line');

        if (cmd_input != null && cmd_input instanceof HTMLInputElement) {

            document.addEventListener('keydown', function (event) {

                if (event.ctrlKey) {
                    return
                }

                cmd_input.focus()
            });

            cmd_input.addEventListener("keyup", async function (e) {
                if (e.key == "Enter") {

                    //
                    // hide the keyboard
                    //
                    if (true == utils.isMobile()) {
                        cmd_input.blur()
                    }

                    const cmd_line = cmd_input.value
                    cmd_input.value = ""

                    if (cmd_line.length > 0) {
                        await on_chat_cb(results_container, cmd_line)
                    }
                }
                else if (e.key == "Escape") {
                    cmd_input.value = ""
                }
            })
        }
        else {
            console.error("couldn't find the search input")
        }
    }
}


/**
 * @param {string} q
 */
async function process_main_query(q) {

    const result = document.getElementById("results")

    if (result != null && result instanceof HTMLElement) {

        add_chat_response(result, q, false, "user")

        const req = {
            "cmd": "/chat",
            "args": q
        }

        let res = await utils.fetch_post_json("/api/cmd", req)
        let response = "😢"

        if (null != res) {
            response = res["data"]
        }

        add_chat_response(result, response, true, "system")
    }
    else {
        console.error("couldn't find results")
    }
}

async function main() {

    var q = null

    const search = window.location.search;

    if (search != null && search.length > 0) {
        const urlParams = new URLSearchParams(search);
        q = urlParams.get('q')
    }

    if (window.location.pathname == "/chat.html") {
        init_cmd_line()

        if (null != q) {
            await process_main_query(q)
        }
    }
    else {
        init_search_bar(q)
    }
}

await main()