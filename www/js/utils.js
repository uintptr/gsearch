//@ts-check

/**
 * @param {string} url
 * @returns {Promise<any | null>}
 */
export async function fetch_as_json(url) {

    try {
        let resp = await fetch(url)

        if (resp.status == 200) {
            return await resp.json()
        }
        else {
            console.log(url + " returned " + resp.status)
        }
    }
    catch (e) {
        console.log("exception")
        console.log(e)
    }

    return null
}



/**
 * @param {HTMLElement} element
 */
export function remove_all_children(element) {
    while (element.firstChild) {
        element.removeChild(element.firstChild);
    }
}

/**
 * @param {string} id
 * @param {string} inner_tag
 * @returns {HTMLElement|null}
 */
export function new_template(id, inner_tag = "div") {

    const entry_template = document.getElementById(id)

    if (entry_template != null && entry_template instanceof HTMLTemplateElement) {

        let new_content = entry_template.content.cloneNode(true)

        if (new_content != null && new_content instanceof DocumentFragment) {
            let item = new_content.querySelector(inner_tag)

            if (item != null && item instanceof HTMLElement) {
                return item
            }
        }
    }

    return null
}

/**
 * @param {HTMLElement} component
 * @param {string} selector
 * @param {string} inner_html
 */
export function set_selector_text(component, selector, inner_html) {
    let element = component.querySelector(selector)

    if (element != null && element instanceof HTMLElement) {
        element.innerHTML = inner_html
    }
}