
export function assertFields(request: any, fields: Array<string>) {
    let fieldAbsent = null;

    if (request.get) {
        fieldAbsent = (field: string) => {
            return request.get(field) === null;
        };
    } else {
        fieldAbsent = (field: string) => {
            return request[field] === undefined;
        };
    }
    for (let field of fields) {
        if (fieldAbsent(field)) {
            const error = `${field} is a mandatory field.`;
            throw new Error(error);
        }
    }
}