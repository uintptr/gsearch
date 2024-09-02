//@ts-check

import * as utils from "./utils.js"

export { }


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
 * @param {HTMLElement} container
 * @param {string} response
 * @param {boolean} markdown
 * @param {string | null} chat_source
 */
function add_command_response(container, response, markdown = false, chat_source = null) {

    utils.show_element(container)

    const result = utils.new_template("command_result")

    if (null != result) {

        // to rebuild the context
        if (null != chat_source) {
            result.setAttribute("chat-source", chat_source)
            result.setAttribute("chat-data", response)
        }

        const text_container = result.querySelector("#command_text")

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
 * @param {string} cmdline
*/
async function command_help(container, cmdline) {
    let ret = "```\n"

    ret += "commands:\n"

    for (const key in g_commands) {
        const value = g_commands[key]["help"]
        ret += `    ${key.padEnd(10)}${value}\n`
    }

    ret += "```"

    add_command_response(container, ret, true)
}


/**
 * @param {HTMLElement} container
 * @param {string} cmdline
*/
async function command_search(container, cmdline) {

    add_command_response(container, "results for \"`" + cmdline + "`\"", true)
    await issue_query(container, cmdline)
}

/**
 * @param {HTMLElement} container
 * @param {string} cmdline
*/
async function command_chat(container, cmdline) {

    let history = get_chat_context(container)

    add_command_response(container, cmdline, true, "user")

    const new_entry = {
        "role": "user",
        "content": cmdline
    }

    history.push(new_entry)

    const chat_req = {
        "history": history
    }

    let chat_res = await utils.fetch_post_json("/api/chat", chat_req)

    if ("data" in chat_res && "message" in chat_res["data"]) {
        const message = chat_res["data"]["message"]
        add_command_response(container, message, true, "system")
    }
    else {
        console.error("message not in response")
    }
}

/**
 * @param {HTMLElement} container
 * @param {string} cmdline
*/
async function command_reset(container, cmdline) {
    utils.remove_all_children(container)
    utils.hide_element(container)
}

const g_commands = {
    "/help":
    {
        "help": "This help",
        "callback": command_help
    },
    "/chat":
    {
        "help": "chat with the LLM and hope for the best ¯\\_(ツ)_/¯",
        "callback": command_chat
    },
    "/reset":
    {
        "help": "reset the output window",
        "callback": command_reset
    },
    "/search":
    {
        "help": "Search using GCSE",
        "callback": command_search
    }
}

/**
* @param {string} cmd_line
*/
async function command_line_parser(cmd_line) {

    if (0 == cmd_line.length) {
        return
    }

    const results = document.getElementById("results")

    if (results != null && results instanceof HTMLElement) {

        if (true == cmd_line.startsWith("/")) {

            const comp = cmd_line.split(/\s+/);

            for (const key in g_commands) {

                const value = g_commands[key]

                if (key == comp[0]) {
                    const args = cmd_line.substring(comp[0].length + 1)
                    await value.callback(results, args)
                }
            }
        }
        else {
            // assume this is a chat request
            await command_line_parser("/chat " + cmd_line)
        }
    }
    else {
        console.error("unable to find results container")
    }
}

function init_cmd_line() {

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
                    await command_line_parser(cmd_line)
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

async function main() {


    const search = window.location.search;

    init_cmd_line()

    if (search != null && search.length > 0) {
        const urlParams = new URLSearchParams(search);

        const q = urlParams.get('q')

        if (null != q) {
            await command_line_parser("/search " + q)
        }

        const c = urlParams.get("c")

        if (null != c) {
            await command_line_parser("/chat " + c)
        }
    }
}

await main()