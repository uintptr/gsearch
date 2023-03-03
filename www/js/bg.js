// listen for messages from the main thread

/*
 * @param {string} query
 */

async function fetch_as_json(url) {

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

async function query_chat_gpt(query) {

    let message = await fetch_as_json("/api/chat?q=" + query)

    if (message != null) {
        return message.content
    }

    console.log("chat came up short")

    return null
}

onmessage = async function (event) {

    data = event.data

    if (data != null && data instanceof Array && data.length > 0) {
        if (data[0] == "chat") {

            msg = await query_chat_gpt(data[1])

            if (msg != null) {
                postMessage(["chat", msg])
            }
        }
        else {
            console.log("Unknown command: " + data[0])
        }
    } else {
        console.log("invalid params")
    }
};